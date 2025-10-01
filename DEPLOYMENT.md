# 🚀 Deployment Guide

## Quick Deployment (Recommended)

### Step 1: Deploy Infrastructure & Agent

```bash
./deploy.sh
```

This deploys:

- S3 bucket for video storage
- IAM roles and permissions
- Bedrock AgentCore video agent

### Step 2: Deploy UI with HTTPS

```bash
./deploy-ecs-fargate.sh
```

This deploys:

- ECS Fargate cluster and service
- Application Load Balancer
- CloudFront distribution with HTTPS
- Full IAM permissions (S3, Bedrock, Rekognition)

### Step 3: Upload Videos & Test

```bash
# Upload sample videos
aws s3 cp your-video.mp4 s3://YOUR-BUCKET-NAME/sample-videos/

# Access your HTTPS URL (provided in deployment output)
```

## 🔧 What Gets Deployed

### Infrastructure Stack (`media-video-agent-infrastructure`)

- **S3 Bucket**: Video storage with lifecycle policies
- **IAM Roles**: Permissions for App Runner instance

### ECS Stack (`media-video-agent-ecs`)

- **VPC & Networking**: Public subnets, Internet Gateway, Security Groups
- **Application Load Balancer**: HTTP load balancer for ECS tasks
- **CloudFront Distribution**: HTTPS endpoint with caching disabled for real-time updates
- **ECS Fargate**: Containerized Streamlit application
- **IAM Roles**: Full permissions for S3, Bedrock, and Rekognition
- **CloudWatch Logs**: Application logging

### Bedrock AgentCore

- **Video Agent**: AI agent with video analysis tools
- **Memory**: Persistent conversation history
- **Tools**: Video listing, analysis, thumbnail extraction, face/celebrity detection

## 🌐 URLs

After deployment, you'll get:

- **HTTPS URL**: `https://xxxxx.cloudfront.net` (Recommended)
- **HTTP URL**: `http://xxxxx.elb.amazonaws.com` (Direct ALB access)

## 🔒 Security Features

- **HTTPS**: CloudFront provides SSL/TLS encryption
- **IAM Roles**: Least-privilege access with managed policies
- **VPC**: Isolated network environment
- **Security Groups**: Restricted network access

## 💰 Cost Estimate

- **ECS Fargate**: ~$15-30/month (0.25 vCPU, 0.5 GB RAM)
- **Application Load Balancer**: ~$16/month
- **CloudFront**: ~$1-5/month (depending on usage)
- **S3 Storage**: ~$1-10/month (depending on video library size)
- **Bedrock AgentCore**: Usage-based pricing
- **Total**: ~$35-65/month for production deployment

## 🗑️ Cleanup

To remove all resources:

```bash
./cleanup.sh
```

This will delete:

- ECS Fargate stack (including VPC, ALB, CloudFront)
- Infrastructure stack (S3 bucket, IAM roles)
- ECR repository and Docker images
- Bedrock AgentCore agent

## 🐛 Troubleshooting

### Common Issues

1. **Agent deployment fails**

   - Check IAM permissions for Bedrock AgentCore
   - Ensure you're in us-west-2 region

2. **ECS service fails to start**

   - Check CloudWatch logs: `/ecs/media-video-agent-ecs`
   - Verify Docker image architecture (should be linux/amd64)

3. **UI not accessible**

   - Wait 5-10 minutes for CloudFront distribution to deploy
   - Check ECS service status in AWS Console

4. **WebSocket connection issues**
   - Use HTTPS URL (CloudFront) instead of HTTP (ALB)
   - Clear browser cache and cookies

### Monitoring

- **ECS Console**: Monitor service health and task status
- **CloudWatch Logs**: Application logs and errors
- **CloudFront Console**: Distribution status and metrics
- **ALB Console**: Target group health and traffic

## 🔧 Advanced Configuration

### Custom Domain (Optional)

To use your own domain:

1. Create SSL certificate in ACM
2. Update CloudFront distribution to use custom certificate
3. Create Route 53 record pointing to CloudFront

### Scaling

ECS service can be configured to auto-scale based on:

- CPU utilization
- Memory utilization
- Request count per target

### Security Enhancements

- Enable WAF on CloudFront for additional protection
- Use private subnets with NAT Gateway for enhanced security
- Enable VPC Flow Logs for network monitoring
