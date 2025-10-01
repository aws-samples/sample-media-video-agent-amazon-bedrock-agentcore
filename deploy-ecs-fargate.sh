#!/bin/bash

# Deploy Video Agent UI to ECS Fargate with Application Load Balancer
# This provides better WebSocket support than App Runner

set -e

# Configuration
INFRA_STACK_NAME="media-video-agent-infrastructure"
ECS_STACK_NAME="media-video-agent-ecs"
REGION="us-west-2"
REPOSITORY_NAME="video-agent-ui"

echo "🚀 Deploying Video Agent UI to ECS Fargate"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is required"
    exit 1
fi

if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "❌ AWS CLI is not configured"
    exit 1
fi

# Get AWS account info
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

echo "📋 Configuration:"
echo "   Account ID: $ACCOUNT_ID"
echo "   Region: $REGION"
echo "   ECS Stack: $ECS_STACK_NAME"
echo ""

# Check if infrastructure exists
if ! aws cloudformation describe-stacks --stack-name $INFRA_STACK_NAME --region $REGION > /dev/null 2>&1; then
    echo "❌ Infrastructure stack not found. Please run './deploy-full-iac.sh' first"
    exit 1
fi

# Get infrastructure outputs
BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name $INFRA_STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`VideoStorageBucketName`].OutputValue' \
    --output text)

# Get Agent ARN
if [ -f ".bedrock_agentcore.yaml" ]; then
    AGENT_ARN=$(grep "agent_arn:" .bedrock_agentcore.yaml | head -1 | cut -d' ' -f4)
    if [ -z "$AGENT_ARN" ]; then
        read -p "Please enter your Agent ARN: " AGENT_ARN
    fi
else
    read -p "Please enter your Agent ARN: " AGENT_ARN
fi

echo "🔧 Deployment Configuration:"
echo "   S3 Bucket: $BUCKET_NAME"
echo "   Agent ARN: $AGENT_ARN"
echo ""

# Step 1: Create ECR repository if it doesn't exist
echo "📦 Step 1: Setting up ECR repository..."
if aws ecr describe-repositories --repository-names $REPOSITORY_NAME --region $REGION > /dev/null 2>&1; then
    echo "✅ ECR repository '$REPOSITORY_NAME' already exists"
else
    aws ecr create-repository --repository-name $REPOSITORY_NAME --region $REGION
    echo "✅ ECR repository '$REPOSITORY_NAME' created"
fi

# Step 2: Build and push Docker image
echo "🐳 Step 2: Building and pushing Docker image..."

# Login to ECR
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_URI

# Build and push image
docker build --platform linux/amd64 -f Dockerfile.ui -t $REPOSITORY_NAME .
docker tag $REPOSITORY_NAME:latest $ECR_URI/$REPOSITORY_NAME:latest
docker push $ECR_URI/$REPOSITORY_NAME:latest

ECR_IMAGE_URI="$ECR_URI/$REPOSITORY_NAME:latest"
echo "✅ Docker image pushed: $ECR_IMAGE_URI"
echo ""

# Step 3: Deploy ECS Fargate stack
echo "☁️  Step 3: Deploying ECS Fargate infrastructure..."

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

# Step 4: Wait for service to be stable
echo "⏳ Waiting for ECS service to be stable..."
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
echo "🎉 Deployment completed successfully!"
echo "================================="
echo ""
echo "📋 Deployment Summary:"
echo "   Infrastructure Stack: $INFRA_STACK_NAME"
echo "   ECS Stack: $ECS_STACK_NAME"
echo "   S3 Bucket: $BUCKET_NAME"
echo "   Agent ARN: $AGENT_ARN"
echo "   Service URL: $SERVICE_URL"
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
echo "📊 Monitor your service:"
echo "   ECS Console: https://console.aws.amazon.com/ecs/home?region=$REGION#/clusters/$CLUSTER_NAME/services"
echo "   CloudWatch Logs: https://console.aws.amazon.com/cloudwatch/home?region=$REGION#logsV2:log-groups/log-group/%2Fecs%2F$ECS_STACK_NAME"
echo ""
echo "🗑️  To clean up resources:"
echo "   aws cloudformation delete-stack --stack-name $ECS_STACK_NAME --region $REGION"
echo "   aws cloudformation delete-stack --stack-name $INFRA_STACK_NAME --region $REGION"
echo "   aws ecr delete-repository --repository-name $REPOSITORY_NAME --region $REGION --force"