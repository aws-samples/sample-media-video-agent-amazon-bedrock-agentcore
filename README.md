# AWS Media Video Agent 🎬

An AI-powered video analysis solution that combines AWS Bedrock AgentCore, Amazon Rekognition, and Streamlit to create an intelligent video library assistant. Upload videos to S3, chat with your AI agent to analyze content, extract thumbnails, detect faces and celebrities, and get intelligent insights about your video collection.

![Architecture](https://img.shields.io/badge/AWS-Bedrock%20AgentCore-orange) ![Architecture](https://img.shields.io/badge/AWS-ECS%20Fargate-blue) ![Architecture](https://img.shields.io/badge/AI-Video%20Analysis-green)

## ⚠️ Important Disclaimer

**This is a demonstration/sample project designed for learning and prototyping purposes only.**

This code is NOT production-ready. Before deploying to production, you MUST address the security considerations listed in the Security section below.

## 🎯 Features

- **🤖 AI Video Analysis**: Uses Amazon Bedrock's TwelveLabs Pegasus model for intelligent content analysis
- **📸 Thumbnail Generation**: Extract video thumbnails at specific timestamps using ffmpeg
- **👤 Face & Celebrity Detection**: Leverage Amazon Rekognition for face and celebrity recognition
- **💬 Interactive Chat Interface**: Streamlit-based web UI for natural language interaction
- **🧠 Persistent Memory**: Conversation history using Bedrock AgentCore Memory
- **☁️ Scalable Deployment**: Deploy on AWS App Runner with automatic scaling

## 🚀 Quick Start - One-Click Deployment

### Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.9+ installed
- Docker installed

### Deploy Everything with One Command

```bash
./deploy-complete.sh
```

This script will automatically:

1. ✅ Deploy S3 infrastructure
2. ✅ Deploy Bedrock Video Agent with ffmpeg
3. ✅ Build and push Docker image to ECR
4. ✅ Deploy ECS Fargate with CloudFront and WAF
5. ✅ Configure all security settings
6. ✅ Wait for everything to be ready

**Time**: ~15-20 minutes

After deployment completes, you'll receive:

- CloudFront HTTPS URL for accessing the application
- S3 bucket name for uploading videos
- Agent ARN and other configuration details

### Upload Videos

```bash
aws s3 cp your-video.mp4 s3://YOUR-BUCKET-NAME/sample-videos/
```

### Clean Up

To remove all deployed resources:

```bash
./cleanup.sh
```

## 📁 Project Structure

```
media-video-agent/
├── README.md                           # This file
├── video_agentcore.py                  # Main agent logic with AI tools
├── video_agent_ui.py                   # Streamlit web interface
├── deploy_video_agent_with_ffmpeg.py   # Agent deployment script
├── deploy-complete.sh                  # One-click deployment script
├── cleanup.sh                          # Resource cleanup script
├── media-storage.yaml                  # CloudFormation: S3 bucket and IAM roles
├── ecs-fargate-ui.yaml                 # CloudFormation: ECS, CloudFront, ALB, WAF
├── Dockerfile.ui                       # Docker container for Streamlit UI
├── requirements.txt                    # Python dependencies
├── LICENSE                             # MIT license
└── .gitignore                          # Git ignore file
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

## � Sescurity Considerations

**⚠️ This demo uses simplified security settings. Before production deployment, address these issues:**

### Known Security Issues

1. **Path Traversal Vulnerability**

   - **Issue**: User-provided S3 keys in `video_agentcore.py` are used directly in file operations without validation
   - **Risk**: Attackers could potentially access/overwrite files outside intended directories
   - **Fix Required**: Implement input validation and sanitization for all S3 keys before file operations

2. **Overly Permissive IAM Policies**

   - **Issue**: Uses `FullAccess` IAM policies (S3FullAccess, RekognitionFullAccess, etc.)
   - **Risk**: Grants more permissions than necessary, violating least-privilege principle
   - **Fix Required**: Replace all FullAccess policies with specific, least-privilege policies scoped to required resources

3. **No Authentication**
   - **Issue**: Streamlit UI has no login system or user authentication
   - **Risk**: Anyone with the URL can access the application
   - **Fix Required**: Implement authentication (e.g., AWS Cognito, OAuth, or API keys)

### Current Security Features

- ✅ S3 bucket blocks public access by default
- ✅ CloudFront enforces HTTPS
- ✅ ALB restricted to CloudFront IPs only
- ✅ AWS WAF with OWASP Top 10 protection and rate limiting
- ✅ No hardcoded credentials (uses IAM roles)

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
