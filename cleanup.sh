#!/bin/bash

# Cleanup script for AWS Media Video Agent
# This script removes all deployed resources

set -e

# Configuration
INFRA_STACK_NAME="media-video-agent-infrastructure"
ECS_STACK_NAME="media-video-agent-ecs"
REGION="us-east-1"
REPOSITORY_NAME="video-agent-ui"
AGENTCORE_STACK_NAME="AgentCore-MediaVideoAgent-default"

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
        # The bucket is versioned: remove old versions and delete markers too,
        # otherwise CloudFormation cannot delete the non-empty bucket.
        while true; do
            VERSIONS=$(aws s3api list-object-versions --bucket "$BUCKET_NAME" --region $REGION --max-items 1000 \
                --query '{Objects: [Versions, DeleteMarkers][][].{Key: Key, VersionId: VersionId}}' --output json)
            if [ "$(echo "$VERSIONS" | grep -c '"Key"')" -eq 0 ]; then
                break
            fi
            aws s3api delete-objects --bucket "$BUCKET_NAME" --region $REGION --delete "$VERSIONS" > /dev/null
        done
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

# Step 5: Delete the AgentCore stack (runtime, memory, ECR repo, CodeBuild project)
echo "🗑️  Step 5: Deleting AgentCore Runtime stack..."
if aws cloudformation describe-stacks --stack-name $AGENTCORE_STACK_NAME --region $REGION > /dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name $AGENTCORE_STACK_NAME --region $REGION
    echo "   Waiting for AgentCore stack deletion..."
    aws cloudformation wait stack-delete-complete --stack-name $AGENTCORE_STACK_NAME --region $REGION
    echo "✅ AgentCore stack deleted"
else
    echo "⚠️  AgentCore stack not found, skipping"
fi
echo ""

# Step 6: Reset local deployment state
echo "🧹 Step 6: Resetting local deployment state..."
echo '{ "targets": {} }' > agentcore/.cli/deployed-state.json
echo '[]' > agentcore/aws-targets.json
rm -f .env
echo "✅ Local state reset"
echo ""

echo "🎉 Cleanup completed successfully!"
echo ""
echo "📋 Summary:"
echo "   ✅ ECS Fargate stack deleted (including CloudFront, ALB, WAF)"
echo "   ✅ S3 bucket emptied and deleted"
echo "   ✅ Infrastructure stack deleted"
echo "   ✅ UI ECR repository deleted"
echo "   ✅ AgentCore Runtime, Memory and build resources deleted"
echo "   ✅ Local deployment state reset"
echo ""
echo "💡 Note: Some resources may take a few minutes to fully delete."
echo "   You can verify deletion in the AWS Console."
echo ""
echo "🚀 To redeploy, run: ./deploy-complete.sh"
