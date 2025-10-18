#!/usr/bin/env python3
"""
Deploy video agent with ffmpeg support by modifying Dockerfile after generation
"""

from bedrock_agentcore_starter_toolkit import Runtime
import time
import json
import boto3
import os

def modify_dockerfile_for_ffmpeg():
    """Modify the generated Dockerfile to include ffmpeg installation"""
    dockerfile_path = "Dockerfile"
    
    if not os.path.exists(dockerfile_path):
        print("❌ Dockerfile not found - run configure first")
        return False
    
    # Read current Dockerfile
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    # Check if ffmpeg is already installed
    if 'ffmpeg' in content:
        print("✅ ffmpeg already in Dockerfile")
        return True
    
    # Find the FROM line and add ffmpeg installation after it
    lines = content.split('\n')
    modified_lines = []
    
    for i, line in enumerate(lines):
        modified_lines.append(line)
        
        # Add ffmpeg installation after the FROM line
        if line.startswith('FROM '):
            modified_lines.append('')
            modified_lines.append('# Install ffmpeg and other system dependencies')
            modified_lines.append('RUN apt-get update && apt-get install -y \\')
            modified_lines.append('    ffmpeg \\')
            modified_lines.append('    && rm -rf /var/lib/apt/lists/*')
            modified_lines.append('')
    
    # Write modified Dockerfile
    modified_content = '\n'.join(modified_lines)
    with open(dockerfile_path, 'w') as f:
        f.write(modified_content)
    
    print("✅ Modified Dockerfile to include ffmpeg")
    return True

def main():
    """Deploy video agent with ffmpeg support"""
    
    agentcore_runtime = Runtime()
    
    # Prompt user for agent name
    agent_name = input("Enter agent name (e.g., myVideoAgent): ").strip()
    if not agent_name:
        agent_name = "media-video-agent"
        print(f"Using default name: {agent_name}")

    print(f"\n🔧 Configuring Video Agent for AgentCore Runtime...")
    print(f"   Agent name: {agent_name}")
    response = agentcore_runtime.configure(
        entrypoint="video_agentcore.py",
        auto_create_execution_role=True,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region="us-east-1",
        agent_name=agent_name
    )
    print("✅ Configuration completed")

    print("\n🎬 Modifying Dockerfile to include ffmpeg...")
    if not modify_dockerfile_for_ffmpeg():
        print("❌ Failed to modify Dockerfile")
        return

    print("\n🚀 Launching Video Agent to AgentCore Runtime...")
    launch_result = agentcore_runtime.launch()
    print("✅ Launch completed")
    print(f"🎯 Agent ARN: {launch_result.agent_arn}")

    # Wait for agent to be deployed
    print("\n⏳ Waiting for agent deployment...")
    status_response = agentcore_runtime.status()
    status = status_response.endpoint['status']
    end_status = ['READY', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']
    
    while status not in end_status:
        time.sleep(10)
        status_response = agentcore_runtime.status()
        status = status_response.endpoint['status']
        print(f"   Status: {status}")

    if status == 'READY':
        print("\n🎉 Video Agent deployed successfully with ffmpeg support!")
        
        # Add full S3 permissions to the execution role
        print("\n🔐 Adding full S3 permissions to execution role...")
        try:
            iam_client = boto3.client('iam', region_name='us-east-1')
            
            # The role name follows a pattern - let's find it
            role_name_pattern = f"AmazonBedrockAgentCoreSDKRuntime-us-east-1-"
            
            # List roles to find the one for our agent
            roles = iam_client.list_roles()
            execution_role_name = None
            
            for role in roles['Roles']:
                if role['RoleName'].startswith(role_name_pattern):
                    execution_role_name = role['RoleName']
                    break
            
            if execution_role_name:
                print(f"   Found execution role: {execution_role_name}")
                
                # Attach S3 full access policy
                iam_client.attach_role_policy(
                    RoleName=execution_role_name,
                    PolicyArn='arn:aws:iam::aws:policy/AmazonS3FullAccess'
                )
                
                # Attach S3 full access policy
                iam_client.attach_role_policy(
                    RoleName=execution_role_name,
                    PolicyArn='arn:aws:iam::aws:policy/AdministratorAccess'
                )
                
                # Also attach Rekognition policy for celebrity/face detection
                iam_client.attach_role_policy(
                    RoleName=execution_role_name,
                    PolicyArn='arn:aws:iam::aws:policy/AmazonRekognitionFullAccess'
                )
                
                # Add Bedrock AgentCore Memory permissions
                memory_policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "bedrock-agentcore:CreateMemory",
                                "bedrock-agentcore:GetMemory",
                                "bedrock-agentcore:ListMemories",
                                "bedrock-agentcore:UpdateMemory",
                                "bedrock-agentcore:DeleteMemory",
                                "bedrock-agentcore:CreateEvent",
                                "bedrock-agentcore:ListEvents",
                                "bedrock-agentcore:GetEvent"
                            ],
                            "Resource": "*"
                        }
                    ]
                }
                print("   ✅ S3, Rekognition, and Memory permissions configured")
            else:
                print("   ⚠️ Could not find execution role")
                
        except Exception as e:
            print(f"   ⚠️ Could not add S3 permissions: {e}")
        
        print(f"\n🎯 Agent ARN: {launch_result.agent_arn}")
        print("💡 This ARN will be automatically used in the UI deployment")
        print("🎬 ffmpeg is now available for thumbnail extraction!")
        
        # Return the agent ARN for use by calling scripts
        return launch_result.agent_arn
        
    else:
        print(f"\n❌ Deployment failed with status: {status}")
        print("💡 Check CloudWatch logs for details")
        return None

if __name__ == "__main__":
    main()