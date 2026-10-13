#!/bin/bash

# Complete one-click deployment for AWS Media Video Agent
# Deploys: S3 storage, the agent on Amazon Bedrock AgentCore Runtime (via the
# AgentCore CLI), and the Streamlit UI on ECS Fargate behind CloudFront + WAF.

set -euo pipefail

# Configuration
INFRA_STACK_NAME="media-video-agent-infrastructure"
ECS_STACK_NAME="media-video-agent-ecs"
REGION="${AWS_REGION:-us-east-1}"
BUCKET_PREFIX="media-video-agent"
REPOSITORY_NAME="video-agent-ui"
AGENTCORE_TARGET="default"

echo "🎬 AWS Media Video Agent - Complete One-Click Deployment"
echo "======================================================="
echo ""

# Check prerequisites
echo "🔍 Checking prerequisites..."
for cmd in aws node npm uv python3; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "❌ '$cmd' is required but not installed"
        exit 1
    fi
done

if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "❌ AWS CLI is not configured"
    exit 1
fi

# Container CLI for the UI image: Docker or Finch (override with CONTAINER_CLI=...)
CONTAINER_CLI="${CONTAINER_CLI:-}"
if [ -z "$CONTAINER_CLI" ]; then
    for cli in docker finch; do
        if command -v "$cli" &> /dev/null && "$cli" info > /dev/null 2>&1; then
            CONTAINER_CLI="$cli"
            break
        fi
    done
fi
if [ -z "$CONTAINER_CLI" ]; then
    echo "❌ No running container engine found. Start Docker, or run 'finch vm start'."
    exit 1
fi
echo "   Container CLI: $CONTAINER_CLI"

# The legacy Python starter toolkit also installs an 'agentcore' command that
# can shadow the new CLI on PATH, so resolve the npm-installed binary directly.
NPM_BIN="$(npm prefix -g)/bin"
AGENTCORE="$NPM_BIN/agentcore"
if [ ! -x "$AGENTCORE" ]; then
    echo "📦 Installing the AgentCore CLI (@aws/agentcore)..."
    npm install -g @aws/agentcore
fi
echo "   AgentCore CLI: $("$AGENTCORE" --version)"
echo "✅ Prerequisites check completed"
echo ""

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

echo "📋 Deployment Configuration:"
echo "   Account ID: $ACCOUNT_ID"
echo "   Region: $REGION"
echo "   Infrastructure Stack: $INFRA_STACK_NAME"
echo "   ECS Stack: $ECS_STACK_NAME"
echo ""

# Step 1: Deploy Infrastructure
echo "☁️  Step 1: Deploying infrastructure (S3 bucket)..."
aws cloudformation deploy \
    --template-file media-storage.yaml \
    --stack-name "$INFRA_STACK_NAME" \
    --parameter-overrides BucketPrefix="$BUCKET_PREFIX" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"

BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$INFRA_STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`VideoStorageBucketName`].OutputValue' \
    --output text)

echo "✅ Infrastructure deployed successfully"
echo "📦 S3 Bucket: $BUCKET_NAME"
echo ""

# Step 2: Deploy the agent with the AgentCore CLI
echo "🤖 Step 2: Deploying video agent to AgentCore Runtime..."
echo "   (the container image, with ffmpeg, is built in AWS CodeBuild)"

# Point the AgentCore deployment target at the current account and region.
cat > agentcore/aws-targets.json << EOF
[
  {
    "name": "$AGENTCORE_TARGET",
    "description": "Media video agent deployment target",
    "account": "$ACCOUNT_ID",
    "region": "$REGION"
  }
]
EOF

(cd agentcore/cdk && npm ci --no-audit --no-fund --silent)
AWS_REGION="$REGION" "$AGENTCORE" deploy --target "$AGENTCORE_TARGET" --yes

AGENT_ARN=$(python3 -c "
import json
state = json.load(open('agentcore/.cli/deployed-state.json'))
print(state['targets']['$AGENTCORE_TARGET']['resources']['runtimes']['VideoAgent']['runtimeArn'])
")

echo "✅ Video agent deployed successfully"
echo "🤖 Agent ARN: $AGENT_ARN"
echo ""

# Step 3: Create ECR repository for the UI if it doesn't exist
echo "📦 Step 3: Setting up ECR repository..."
if aws ecr describe-repositories --repository-names "$REPOSITORY_NAME" --region "$REGION" > /dev/null 2>&1; then
    echo "✅ ECR repository '$REPOSITORY_NAME' already exists"
else
    aws ecr create-repository --repository-name "$REPOSITORY_NAME" --region "$REGION" \
        --image-scanning-configuration scanOnPush=true > /dev/null
    echo "✅ ECR repository '$REPOSITORY_NAME' created"
fi

# Step 4: Build and push the UI image
echo "🐳 Step 4: Building and pushing the UI image..."
aws ecr get-login-password --region "$REGION" | "$CONTAINER_CLI" login --username AWS --password-stdin "$ECR_URI"
"$CONTAINER_CLI" build --platform linux/amd64 -f Dockerfile.ui -t "$REPOSITORY_NAME" .
"$CONTAINER_CLI" tag "$REPOSITORY_NAME:latest" "$ECR_URI/$REPOSITORY_NAME:latest"
"$CONTAINER_CLI" push "$ECR_URI/$REPOSITORY_NAME:latest"

ECR_IMAGE_URI="$ECR_URI/$REPOSITORY_NAME:latest"
echo "✅ Docker image pushed: $ECR_IMAGE_URI"
echo ""

# Step 5: Ensure ECS service-linked role exists
echo "🔐 Step 5: Ensuring ECS service-linked role exists..."
if ! aws iam get-role --role-name AWSServiceRoleForECS > /dev/null 2>&1; then
    echo "   Creating ECS service-linked role..."
    aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com > /dev/null
    echo "   Waiting for IAM role propagation (30 seconds)..."
    sleep 30
else
    echo "   ✅ ECS service-linked role exists"
fi
echo ""

# Step 6: Deploy ECS Fargate stack
echo "☁️  Step 6: Deploying ECS Fargate + CloudFront infrastructure..."
aws cloudformation deploy \
    --template-file ecs-fargate-ui.yaml \
    --stack-name "$ECS_STACK_NAME" \
    --parameter-overrides \
        AgentArn="$AGENT_ARN" \
        S3BucketName="$BUCKET_NAME" \
        ECRImageUri="$ECR_IMAGE_URI" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"

stack_output() {
    aws cloudformation describe-stacks \
        --stack-name "$ECS_STACK_NAME" \
        --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey==\`$1\`].OutputValue" \
        --output text
}

ALB_URL=$(stack_output LoadBalancerURL)
SERVICE_URL=$(stack_output CloudFrontURL)
CLUSTER_NAME=$(stack_output ECSClusterName)
SERVICE_NAME=$(stack_output ECSServiceName)

echo "✅ ECS Fargate deployment completed successfully"
echo ""

# The image tag is always :latest, so on re-runs CloudFormation sees no change.
# Force a rollout so the service picks up the image that was just pushed.
aws ecs update-service --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
    --force-new-deployment --region "$REGION" > /dev/null

# Step 7: Wait for service to be stable
echo "⏳ Step 7: Waiting for ECS service to be stable (5-10 minutes)..."
aws ecs wait services-stable --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" --region "$REGION"

# Save environment variables for local testing
cat > .env << EOF
AGENT_ARN=$AGENT_ARN
S3_BUCKET_NAME=$BUCKET_NAME
AWS_REGION=$REGION
SERVICE_URL=$SERVICE_URL
ALB_URL=$ALB_URL
EOF

echo ""
echo "🎉 Complete deployment successful!"
echo "================================="
echo ""
echo "📋 Deployment Summary:"
echo "   S3 Bucket: $BUCKET_NAME"
echo "   Agent ARN: $AGENT_ARN"
echo "   UI Image:  $ECR_IMAGE_URI"
echo ""
echo "🌐 Your Video Agent UI is available at:"
echo "   HTTPS (Recommended): $SERVICE_URL"
echo ""
echo "🎯 Next Steps:"
echo "1. Upload sample videos:"
echo "   aws s3 cp your-video.mp4 s3://$BUCKET_NAME/sample-videos/"
echo "2. Open the UI, or test the agent from the terminal:"
echo "   $AGENTCORE invoke \"List the videos in bucket $BUCKET_NAME\""
echo ""
echo "📊 Agent logs:  $AGENTCORE logs"
echo "🗑️  Clean up:   ./cleanup.sh"
echo "💾 Environment variables saved to .env"
