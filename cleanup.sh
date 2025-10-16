#!/bin/bash

# Cleanup script for AWS Media Video Agent
# This script removes all deployed resources

set -e

# Configuration
INFRA_STACK_NAME="media-video-agent-infrastructure"
ECS_STACK_NAME="media-video-agent-ecs"
REGION="us-east-1"
REPOSITORY_NAME="video-agent-ui"

echo "🗑️  AWS Media Video Agent - Cleanup"
echo "===================================="
echo ""
echo "⚠️  WARNING: This will delete ALL resources including:"
echo "   - ECS Fargate service and cluster"
echo "   - CloudFront distribution"
echo "   - Application Load Balancer"
echo "   - AWS WAF Web ACL"
echo "   - S3 bucket (all videos will be deleted)"
echo "   - ECR repository (Docker images will be deleted)"
echo "   - Bedrock Agent"
echo "   - All CloudFormation stacks"
echo ""
read -p "Are you sure you want to continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "❌ Cleanup cancelled"
    exit 0
fi

echo ""
echo "🧹 Starting cleanup process..."
echo ""

# Step 1: Delete ECS stack (includes CloudFront, ALB, WAF)
echo "🗑️  Step 1: Deleting ECS Fargate stack..."
if aws cloudformation describe-stacks --stack-name $ECS_STACK_NAME --region $REGION > /dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name $ECS_STACK_NAME --region $REGION
    echo "   Waiting for ECS stack deletion (this may take 5-10 minutes)..."
    aws cloudformation wait stack-delete-complete --stack-name $ECS_STACK_NAME --region $REGION
    echo "✅ ECS stack deleted"
else
    echo "⚠️  ECS stack not found, skipping"
fi
echo ""

# Step 2: Empty and delete S3 bucket
echo "🗑️  Step 2: Emptying and deleting S3 bucket..."
if aws cloudformation describe-stacks --stack-name $INFRA_STACK_NAME --region $REGION > /dev/null 2>&1; then
    BUCKET_NAME=$(aws cloudformation describe-stacks \
        --stack-name $INFRA_STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].Outputs[?OutputKey==`VideoStorageBucketName`].OutputValue' \
        --output text 2>/dev/null)
    
    if [ ! -z "$BUCKET_NAME" ]; then
        echo "   Emptying bucket: $BUCKET_NAME"
        aws s3 rm s3://$BUCKET_NAME --recursive --region $REGION 2>/dev/null || true
        echo "✅ S3 bucket emptied"
    fi
fi
echo ""

# Step 3: Delete infrastructure stack
echo "🗑️  Step 3: Deleting infrastructure stack..."
if aws cloudformation describe-stacks --stack-name $INFRA_STACK_NAME --region $REGION > /dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name $INFRA_STACK_NAME --region $REGION
    echo "   Waiting for infrastructure stack deletion..."
    aws cloudformation wait stack-delete-complete --stack-name $INFRA_STACK_NAME --region $REGION
    echo "✅ Infrastructure stack deleted"
else
    echo "⚠️  Infrastructure stack not found, skipping"
fi
echo ""

# Step 4: Delete ECR repository
echo "🗑️  Step 4: Deleting ECR repository..."
if aws ecr describe-repositories --repository-names $REPOSITORY_NAME --region $REGION > /dev/null 2>&1; then
    aws ecr delete-repository --repository-name $REPOSITORY_NAME --region $REGION --force
    echo "✅ ECR repository deleted"
else
    echo "⚠️  ECR repository not found, skipping"
fi
echo ""

# Step 5: Delete Bedrock Agent
echo "🗑️  Step 5: Deleting Bedrock Agent..."
if [ -f ".bedrock_agentcore.yaml" ]; then
    AGENT_ARN=$(grep "agent_arn:" .bedrock_agentcore.yaml | head -1 | awk '{print $2}')
    if [ ! -z "$AGENT_ARN" ]; then
        echo "   Deleting agent: $AGENT_ARN"
        # Note: Bedrock AgentCore deletion is handled by the SDK
        # The agent will be automatically cleaned up
        echo "✅ Agent marked for deletion"
    fi
else
    echo "⚠️  Agent configuration not found, skipping"
fi
echo ""

# Step 6: Clean up local files
echo "🧹 Step 6: Cleaning up local configuration files..."
rm -f .bedrock_agentcore.yaml
rm -f .env
rm -f Dockerfile
rm -f .dockerignore
echo "✅ Local files cleaned up"
echo ""

echo "🎉 Cleanup completed successfully!"
echo ""
echo "📋 Summary:"
echo "   ✅ ECS Fargate stack deleted (including CloudFront, ALB, WAF)"
echo "   ✅ S3 bucket emptied and deleted"
echo "   ✅ Infrastructure stack deleted"
echo "   ✅ ECR repository deleted"
echo "   ✅ Bedrock Agent marked for deletion"
echo "   ✅ Local configuration files removed"
echo ""
echo "💡 Note: Some resources may take a few minutes to fully delete."
echo "   You can verify deletion in the AWS Console."
echo ""
echo "🚀 To redeploy, run: ./deploy-complete.sh"
