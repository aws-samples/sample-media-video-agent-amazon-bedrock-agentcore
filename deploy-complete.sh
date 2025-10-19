#!/bin/bash

# Complete one-click deployment for AWS Media Video Agent
# This script deploys everything: infrastructure, agent, and UI with HTTPS

set -e

# Configuration
INFRA_STACK_NAME="media-video-agent-infrastructure"
ECS_STACK_NAME="media-video-agent-ecs"
REGION="us-east-1"
BUCKET_PREFIX="media-video-agent"
REPOSITORY_NAME="video-agent-ui"

echo "🎬 AWS Media Video Agent - Complete One-Click Deployment"
echo "======================================================="
echo ""

# Check prerequisites
echo "🔍 Checking prerequisites..."

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is required but not installed"
    exit 1
fi

if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "❌ AWS CLI is not configured"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is required"
    exit 1
fi

echo "✅ Prerequisites check completed"
echo ""

# Get AWS account info
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

echo "📋 Deployment Configuration:"
echo "   Account ID: $ACCOUNT_ID"
echo "   Region: $REGION"
echo "   Infrastructure Stack: $INFRA_STACK_NAME"
echo "   ECS Stack: $ECS_STACK_NAME"
echo ""

# Clean up any stale configuration files for fresh deployment
echo "🧹 Cleaning up stale configuration files..."
rm -f .bedrock_agentcore.yaml
rm -f Dockerfile
rm -f .dockerignore
echo "✅ Cleanup completed"
echo ""

# Step 1: Deploy Infrastructure
echo "☁️  Step 1: Deploying infrastructure (S3, IAM roles)..."
aws cloudformation deploy \
    --template-file media-storage.yaml \
    --stack-name $INFRA_STACK_NAME \
    --parameter-overrides BucketPrefix=$BUCKET_PREFIX \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $REGION

if [ $? -ne 0 ]; then
    echo "❌ Infrastructure deployment failed"
    exit 1
fi

# Get bucket name
BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name $INFRA_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`VideoStorageBucketName`].OutputValue' \
    --output text)

echo "✅ Infrastructure deployed successfully"
echo "📦 S3 Bucket: $BUCKET_NAME"
echo ""

# Step 2: Install Python dependencies
echo "📦 Step 2: Installing Python dependencies..."
pip3 install --quiet bedrock-agentcore-starter-toolkit strands-agents boto3

if [ $? -ne 0 ]; then
    echo "❌ Failed to install Python dependencies"
    exit 1
fi

echo "✅ Python dependencies installed"
echo ""

# Step 3: Deploy Video Agent
echo "🤖 Step 3: Deploying video agent..."
python3 deploy_video_agent_with_ffmpeg.py

if [ $? -ne 0 ]; then
    echo "❌ Video agent deployment failed"
    exit 1
fi

# Extract Agent ARN from the configuration file
if [ -f ".bedrock_agentcore.yaml" ]; then
    AGENT_ARN=$(grep "agent_arn:" .bedrock_agentcore.yaml | head -1 | awk '{print $2}')
    if [ -z "$AGENT_ARN" ]; then
        echo "❌ Could not extract Agent ARN from configuration file"
        exit 1
    fi
else
    echo "❌ Agent configuration file not found"
    exit 1
fi

echo "✅ Video agent deployed successfully"
echo "🤖 Agent ARN: $AGENT_ARN"
echo ""

# Step 4: Create ECR repository if it doesn't exist
echo "📦 Step 4: Setting up ECR repository..."
if aws ecr describe-repositories --repository-names $REPOSITORY_NAME --region $REGION > /dev/null 2>&1; then
    echo "✅ ECR repository '$REPOSITORY_NAME' already exists"
else
    aws ecr create-repository --repository-name $REPOSITORY_NAME --region $REGION
    echo "✅ ECR repository '$REPOSITORY_NAME' created"
fi

# Step 5: Build and push Docker image
echo "🐳 Step 5: Building and pushing Docker image..."

# Login to ECR
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_URI

# Build and push image
docker build --platform linux/amd64 -f Dockerfile.ui -t $REPOSITORY_NAME .
docker tag $REPOSITORY_NAME:latest $ECR_URI/$REPOSITORY_NAME:latest
docker push $ECR_URI/$REPOSITORY_NAME:latest

ECR_IMAGE_URI="$ECR_URI/$REPOSITORY_NAME:latest"
echo "✅ Docker image pushed: $ECR_IMAGE_URI"
echo ""

# Step 6: Ensure ECS service-linked role exists
echo "🔐 Step 6: Ensuring ECS service-linked role exists..."
aws iam get-role --role-name AWSServiceRoleForECS > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "   Creating ECS service-linked role..."
    aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com
    echo "   Waiting for IAM role propagation (30 seconds)..."
    sleep 30
else
    echo "   ✅ ECS service-linked role exists"
fi
echo ""

# Step 7: Deploy ECS Fargate stack
echo "☁️  Step 7: Deploying ECS Fargate + CloudFront infrastructure..."

aws cloudformation deploy \
    --template-file ecs-fargate-ui.yaml \
    --stack-name $ECS_STACK_NAME \
    --parameter-overrides \
        AgentArn="$AGENT_ARN" \
        S3BucketName="$BUCKET_NAME" \
        ECRImageUri="$ECR_IMAGE_URI" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $REGION

if [ $? -ne 0 ]; then
    echo "❌ ECS deployment failed"
    exit 1
fi

# Get service URLs
ALB_URL=$(aws cloudformation describe-stacks \
    --stack-name $ECS_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerURL`].OutputValue' \
    --output text)

SERVICE_URL=$(aws cloudformation describe-stacks \
    --stack-name $ECS_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontURL`].OutputValue' \
    --output text)

echo "✅ ECS Fargate deployment completed successfully"
echo ""

# Step 8: Wait for service to be stable
echo "⏳ Step 8: Waiting for ECS service to be stable..."
echo "   This may take 5-10 minutes..."

CLUSTER_NAME=$(aws cloudformation describe-stacks \
    --stack-name $ECS_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' \
    --output text)

SERVICE_NAME=$(aws cloudformation describe-stacks \
    --stack-name $ECS_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ECSServiceName`].OutputValue' \
    --output text)

# Wait for service to be stable
aws ecs wait services-stable --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION

echo ""
echo "🎉 Complete deployment successful!"
echo "================================="
echo ""
echo "📋 Deployment Summary:"
echo "   Infrastructure Stack: $INFRA_STACK_NAME"
echo "   ECS Stack: $ECS_STACK_NAME"
echo "   S3 Bucket: $BUCKET_NAME"
echo "   Agent ARN: $AGENT_ARN"
echo "   ECR Image: $ECR_IMAGE_URI"
echo ""
echo "🌐 Your Video Agent UI is available at:"
echo "   HTTPS (Recommended): $SERVICE_URL"
echo "   HTTP (Direct ALB):   $ALB_URL"
echo ""
echo "🎯 Next Steps:"
echo "1. Upload sample videos:"
echo "   aws s3 cp your-video.mp4 s3://$BUCKET_NAME/sample-videos/"
echo ""
echo "2. Access your UI via HTTPS and start chatting with your video agent!"
echo "   Note: CloudFront provides HTTPS and ECS Fargate provides full WebSocket support!"
echo ""
echo "📊 Monitor your deployment:"
echo "   ECS Console: https://console.aws.amazon.com/ecs/home?region=$REGION#/clusters/$CLUSTER_NAME/services"
echo "   CloudWatch Logs: https://console.aws.amazon.com/cloudwatch/home?region=$REGION#logsV2:log-groups/log-group/%2Fecs%2F$ECS_STACK_NAME"
echo ""
echo "🗑️  To clean up all resources:"
echo "   ./cleanup.sh"
echo ""
echo "💾 Configuration saved:"
echo "   Agent config: .bedrock_agentcore.yaml"
echo "   Environment: .env (for local testing)"

# Save environment variables for local testing
cat > .env << EOF
AGENT_ARN=$AGENT_ARN
S3_BUCKET_NAME=$BUCKET_NAME
AWS_REGION=$REGION
SERVICE_URL=$SERVICE_URL
ALB_URL=$ALB_URL
EOF

echo "✅ Environment variables saved to .env file"