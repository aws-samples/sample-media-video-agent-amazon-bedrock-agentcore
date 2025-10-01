# AWS Media Video Agent 🎬

An AI-powered video analysis solution that combines AWS Bedrock AgentCore, Amazon Rekognition, and Streamlit to create an intelligent video library assistant. Upload videos to S3, chat with your AI agent to analyze content, extract thumbnails, detect faces and celebrities, and get intelligent insights about your video collection.

![Architecture](https://img.shields.io/badge/AWS-Bedrock%20AgentCore-orange) ![Architecture](https://img.shields.io/badge/AWS-App%20Runner-blue) ![Architecture](https://img.shields.io/badge/AI-Video%20Analysis-green)

## 🎯 Features

- **🤖 AI Video Analysis**: Uses Amazon Bedrock's TwelveLabs Pegasus model for intelligent content analysis
- **📸 Thumbnail Generation**: Extract video thumbnails at specific timestamps using ffmpeg
- **👤 Face & Celebrity Detection**: Leverage Amazon Rekognition for face and celebrity recognition
- **💬 Interactive Chat Interface**: Streamlit-based web UI for natural language interaction
- **🧠 Persistent Memory**: Conversation history using Bedrock AgentCore Memory
- **☁️ Scalable Deployment**: Deploy on AWS App Runner with automatic scaling

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   App Runner    │    │  Bedrock Agent   │    │   S3 Bucket     │
│  (Streamlit UI) │◄──►│     Core         │◄──►│   (Videos)      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │   Rekognition    │
                       │ (Face Detection) │
                       └──────────────────┘
```

## 🚀 Quick Start

### 🎯 Deployment Options

**Option 1: ECS Fargate (Recommended - Best for Streamlit)**

- ✅ Full WebSocket support
- ✅ Production-ready with load balancer
- ✅ Auto-scaling and high availability
- ✅ Better monitoring and logging

**Option 2: App Runner (Simple but WebSocket limitations)**

- ✅ Easiest deployment
- ⚠️ WebSocket connection issues with Streamlit
- ✅ Serverless scaling

**Option 3: EC2 (Simple and reliable)**

- ✅ Full control and compatibility
- ✅ Easy troubleshooting
- ⚠️ Manual scaling and management

### Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.9+ installed
- Docker installed (for App Runner deployment)
- AWS Account with access to:
  - Bedrock AgentCore
  - Amazon Rekognition
  - Amazon S3
  - AWS App Runner

### Step 1: Deploy Infrastructure

Deploy the S3 bucket and IAM roles:

```bash
aws cloudformation deploy \
  --template-file media-storage.yaml \
  --stack-name media-video-agent-infrastructure \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2 \
  --parameter-overrides BucketPrefix=my-video-agent
```

Get the bucket name from the stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name media-video-agent-infrastructure \
  --query 'Stacks[0].Outputs[?OutputKey==`VideoStorageBucketName`].OutputValue' \
  --output text
```

### Step 2: Deploy the Video Agent

Install required Python packages:

```bash
pip install bedrock-agentcore-starter-toolkit strands-agents boto3
```

Deploy the agent:

```bash
python deploy_video_agent_with_ffmpeg.py
```

**Save the Agent ARN** from the output - you'll need it for the UI deployment.

### Step 3: Upload Sample Videos

Upload your videos to the S3 bucket:

```bash
aws s3 cp your-video.mp4 s3://YOUR-BUCKET-NAME/sample-videos/
```

### Step 4: Deploy the Web Interface

#### Option A: AWS App Runner (Recommended)

1. **Create ECR Repository:**

```bash
aws ecr create-repository --repository-name video-agent-ui --region us-west-2
```

2. **Build and Push Docker Image:**

```bash
# Get your account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Login to ECR
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com

# Build and push
docker build -t video-agent-ui .
docker tag video-agent-ui:latest $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/video-agent-ui:latest
docker push $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/video-agent-ui:latest
```

3. **Create App Runner Service:**
   - Go to AWS Console > App Runner
   - Create Service > Container registry > Amazon ECR
   - Select your `video-agent-ui` repository
   - Configure:
     - Port: 8000
     - Environment variables:
       - `AGENT_ARN`: Your agent ARN from Step 2
       - `S3_BUCKET_NAME`: Your bucket name from Step 1
       - `AWS_REGION`: us-west-2

#### Option B: Local Testing

```bash
# Install Streamlit
pip install streamlit boto3

# Set environment variables
export AGENT_ARN="your-agent-arn"
export S3_BUCKET_NAME="your-bucket-name"

# Run locally
streamlit run video_agent_ui.py
```

## 📁 Project Structure

```
media-video-agent/
├── README.md                           # This file
├── video_agentcore.py                  # Main agent logic with AI tools
├── deploy_video_agent_with_ffmpeg.py   # Agent deployment script
├── video_agent_ui.py                   # Streamlit web interface
├── media-storage.yaml                  # CloudFormation template for S3/IAM
├── ecs-fargate-ui.yaml                 # CloudFormation template for ECS + CloudFront
├── Dockerfile.ui                       # Container for Streamlit UI
├── requirements.txt                    # Python dependencies
├── deploy.sh                          # Infrastructure deployment script
├── deploy-ecs-fargate.sh              # ECS Fargate + CloudFront deployment
├── cleanup.sh                         # Resource cleanup script
├── LICENSE                            # MIT license
└── .gitignore                         # Git ignore file
```

## 🎬 Usage Examples

Once deployed, you can interact with your video agent through natural language:

- **"List all videos in my bucket"**
- **"Analyze the first video and provide a summary"**
- **"Extract thumbnails from all videos at 30 seconds"**
- **"Detect celebrities in the latest video"**
- **"What's the content of the video named 'presentation.mp4'?"**
- **"Generate thumbnails for videos in the 'movies' folder"**

## 🔧 Configuration

### Environment Variables

- `AGENT_ARN`: Bedrock AgentCore agent ARN (required)
- `S3_BUCKET_NAME`: S3 bucket for video storage (required)
- `AWS_REGION`: AWS region (default: us-west-2)

### Agent Tools

The video agent includes these built-in tools:

- `list_s3_videos()`: List and browse videos in S3
- `analyze_video_with_pegasus()`: AI-powered content analysis
- `extract_video_thumbnail()`: Generate thumbnails using ffmpeg
- `detect_faces_in_video()`: Face detection with Rekognition
- `detect_celebrities_in_video()`: Celebrity recognition

## 💰 Cost Estimation

### Monthly Costs (Approximate)

- **App Runner**: $5-25/month (scales to zero when idle)
- **Bedrock AgentCore**: $10-50/month (usage-based)
- **S3 Storage**: $1-10/month (depends on video library size)
- **Rekognition**: Pay-per-use for face/celebrity detection
- **Bedrock Pegasus**: Pay-per-use for video analysis

### Cost Optimization Tips

- App Runner automatically scales to zero when not in use
- S3 lifecycle policies clean up old thumbnails after 30 days
- Rekognition jobs are only triggered on demand
- Use smaller video files for testing to minimize costs

## 🔒 Security

- **S3 Bucket**: Blocks public access by default
- **IAM Roles**: Use least-privilege permissions
- **App Runner**: Provides HTTPS endpoints automatically
- **No Hardcoded Credentials**: Uses AWS IAM roles and environment variables
- **VPC**: Can be deployed in private subnets (optional)

## 🛠️ Development

### Local Development Setup

1. **Clone the repository:**

```bash
git clone https://github.com/your-username/aws-media-video-agent.git
cd aws-media-video-agent
```

2. **Install dependencies:**

```bash
pip install -r requirements.txt
```

3. **Configure AWS credentials:**

```bash
aws configure
```

4. **Test the agent locally:**

```bash
python video_agentcore.py
```

### Adding New Features

To extend the agent with new capabilities:

1. **Add new tools** in `video_agentcore.py`:

```python
@tool
def your_new_tool(param: str) -> dict:
    """Your tool description"""
    # Your implementation
    return {"result": "success"}
```

2. **Register the tool** with the agent:

```python
agent = Agent(
    name="video_agent",
    model=BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
    system_prompt=VIDEO_AGENT_PROMPT,
    tools=[
        list_s3_videos,
        analyze_video_with_pegasus,
        extract_video_thumbnail,
        your_new_tool  # Add your new tool here
    ]
)
```

3. **Update the UI** if needed in `video_agent_ui.py`

## 🐛 Troubleshooting

### Common Issues

1. **Agent deployment fails**

   - Check IAM permissions for Bedrock AgentCore
   - Ensure you're in a supported region (us-west-2 recommended)
   - Verify Python dependencies are installed

2. **UI can't connect to agent**

   - Verify the `AGENT_ARN` environment variable is correct
   - Check that the agent is in "READY" status
   - Ensure IAM roles have proper permissions

3. **Video analysis fails**

   - Confirm videos are in supported formats (MP4, MOV, AVI)
   - Check S3 bucket permissions
   - Verify Bedrock model access

4. **Thumbnail extraction fails**
   - Ensure ffmpeg is installed in the container
   - Check video file accessibility in S3
   - Verify sufficient disk space for temporary files

### Logs and Monitoring

- **Agent Logs**: CloudWatch Logs for Bedrock AgentCore
- **UI Logs**: App Runner service logs in CloudWatch
- **Infrastructure**: CloudFormation stack events

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Issues**: Open an issue on GitHub
- **Documentation**: Check the AWS Bedrock AgentCore documentation
- **Community**: Join the AWS Developer Community

## 🙏 Acknowledgments

- AWS Bedrock team for AgentCore platform
- TwelveLabs for the Pegasus video analysis model
- Streamlit team for the amazing web framework
- ffmpeg community for video processing tools

---

**Built with ❤️ for the AWS community**

Ready to analyze your videos with AI? Let's get started! 🚀
