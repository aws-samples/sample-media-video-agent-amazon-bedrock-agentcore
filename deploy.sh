#!/bin/bash

# One-click deployment script for AWS Media Video Agent
# This script deploys the complete solution to your AWS account

set -e

# Configuration
STACK_NAME="media-video-agent-infrastructure"
REGION="us-west-2"
BUCKET_PREFIX="media-video-agent"

echo "🎬 AWS Media Video Agent - One-Click Deployment"
echo "=============================================="
echo ""

# Check prerequisites
echo "🔍 Checking prerequisites..."

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is required but not installed"
    echo "   Please install AWS CLI: https://aws.amazon.com/cli/"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "❌ AWS CLI is not configured or you don't have permissions"
    echo "   Please run 'aws configure' first"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "⚠️  Docker not found - you can still deploy the agent, but UI deployment will be manual"
    DOCKER_AVAILABLE=false
else
    DOCKER_AVAILABLE=true
fi

echo "✅ Prerequisites check completed"
echo ""

# Get AWS account info
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "📋 Deploying to AWS Account: $ACCOUNT_ID"
echo "📋 Region: $REGION"
echo ""

# Step 1: Deploy Infrastructure
echo "☁️  Step 1: Deploying infrastructure (S3, IAM roles)..."
aws cloudformation deploy \
    --template-file media-storage.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides BucketPrefix=$BUCKET_PREFIX \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $REGION

if [ $? -ne 0 ]; then
    echo "❌ Infrastructure deployment failed"
    exit 1
fi

# Get bucket name
BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
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

echo "✅ Video agent deployed successfully"
echo ""

# Step 4: UI Deployment Instructions
echo "🌐 Step 4: UI Deployment Options"
echo "================================"
echo ""

if [ "$DOCKER_AVAILABLE" = true ]; then
    echo "Option A: Deploy to AWS App Runner (Recommended)"
    echo "------------------------------------------------"
    echo ""
    echo "1. Create ECR repository:"
    echo "   aws ecr create-repository --repository-name video-agent-ui --region $REGION"
    echo ""
    echo "2. Build and push Docker image:"
    echo "   aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
    echo "   docker build -t video-agent-ui ."
    echo "   docker tag video-agent-ui:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/video-agent-ui:latest"
    echo "   docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/video-agent-ui:latest"
    echo ""
    echo "3. Create App Runner service in AWS Console:"
    echo "   - Go to AWS Console > App Runner > Create Service"
    echo "   - Choose 'Container registry' > 'Amazon ECR'"
    echo "   - Select your video-agent-ui repository"
    echo "   - Set port to 8000"
    echo "   - Add environment variables (see below)"
    echo ""
else
    echo "Docker not available - manual UI deployment required"
    echo ""
fi

echo "Option B: Run locally for testing"
echo "---------------------------------"
echo "   pip install streamlit boto3"
echo "   streamlit run video_agent_ui.py"
echo ""

echo "🔧 Required Environment Variables for UI:"
echo "========================================="
echo "AGENT_ARN=<your-agent-arn-from-step-3>"
echo "S3_BUCKET_NAME=$BUCKET_NAME"
echo "AWS_REGION=$REGION"
echo ""

echo "📁 Sample Video Upload:"
echo "======================="
echo "Upload your videos to: s3://$BUCKET_NAME/sample-videos/"
echo "Example: aws s3 cp your-video.mp4 s3://$BUCKET_NAME/sample-videos/"
echo ""

echo "🎉 Deployment completed successfully!"
echo ""
echo "🎯 Next Steps:"
echo "1. Upload sample videos to S3"
echo "2. Deploy the UI using one of the options above"
echo "3. Access your video agent and start chatting!"
echo ""
echo "💡 Need help? Check the README.md for detailed instructions"