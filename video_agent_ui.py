import streamlit as st
import boto3
import json
import time
import re
from datetime import datetime
from urllib.parse import urlparse, quote

# Page configuration
st.set_page_config(
    page_title="🎬 Video Agent Chat",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

def extract_s3_urls(text):
    """Extract S3 URLs from text, handling special characters and markdown"""
    # Clean up the text first - remove markdown backticks and extra formatting
    cleaned_text = text.replace('`', '').replace('###', '')
    
    urls = []
    
    # Pattern 1: Extract presigned URLs from markdown links
    # Look for [text](https://bucket.s3.amazonaws.com/path?params)
    markdown_pattern = r'\[([^\]]+)\]\((https://[^/\s]+\.s3\.amazonaws\.com/[^)]+)\)'
    markdown_matches = re.findall(markdown_pattern, cleaned_text)
    
    for link_text, url in markdown_matches:
        # Only include if it looks like a thumbnail link
        if any(keyword in link_text.lower() for keyword in ['thumbnail', 'view', 'click', 'image']):
            urls.append(url)
    
    # Pattern 2: Direct presigned URLs (not in markdown)
    # Look for https://bucket.s3.amazonaws.com/path?params
    direct_presigned_pattern = r'(https://[^/\s]+\.s3\.amazonaws\.com/[^\s\)]+)'
    direct_matches = re.findall(direct_presigned_pattern, cleaned_text)
    
    for url in direct_matches:
        # Only include if it has AWS signature parameters (indicating it's a presigned URL)
        if 'AWSAccessKeyId=' in url or 'X-Amz-' in url:
            urls.append(url)
    
    # Pattern 3: Traditional s3:// URLs - more flexible to handle special characters
    s3_pattern = r's3://([^/\s]+)/([^\n\r`]+?)(?=\s|$|\n|\r|`|###)'
    matches = re.findall(s3_pattern, cleaned_text)
    
    for bucket, key in matches:
        # Clean up the key - remove trailing punctuation and whitespace
        key = key.strip().rstrip('.,;:!?')
        # Remove any remaining backticks or markdown formatting
        key = key.replace('`', '').replace('###', '')
        urls.append(f"s3://{bucket}/{key}")
    
    return urls

def generate_presigned_url(s3_url, fallback_bucket_name, expiration=3600):
    """Generate a presigned URL for an S3 object"""
    try:
        s3_client = boto3.client('s3', region_name='us-west-2')
        
        # Extract bucket and key from S3 URL
        if s3_url.startswith('s3://'):
            # Remove s3:// and split into bucket and key
            path = s3_url.replace('s3://', '')
            parts = path.split('/', 1)
            if len(parts) == 2:
                bucket_from_url = parts[0]
                key = parts[1]
                # Use bucket from URL if available, otherwise fallback
                bucket_to_use = bucket_from_url if bucket_from_url else fallback_bucket_name
            else:
                return None
        else:
            return None
        
        # First check if object exists
        try:
            s3_client.head_object(Bucket=bucket_to_use, Key=key)
        except Exception:
            # Try URL encoding the key for special characters
            try:
                encoded_key = quote(key, safe='/')
                s3_client.head_object(Bucket=bucket_to_use, Key=encoded_key)
                key = encoded_key  # Use encoded key if it works
            except Exception:
                return None
        
        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_to_use, 'Key': key},
            ExpiresIn=expiration
        )
        return presigned_url
    except Exception:
        return None

def list_actual_thumbnails(bucket_name):
    """List actual thumbnail files in the S3 bucket"""
    try:
        s3_client = boto3.client('s3', region_name='us-west-2')
        
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix='thumbnails/',
            MaxKeys=50
        )
        
        thumbnails = []
        for obj in response.get('Contents', []):
            key = obj['Key']
            if any(ext in key.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                thumbnails.append(f"s3://{bucket_name}/{key}")
        
        return thumbnails
        
    except Exception:
        # Silently return empty list if listing fails
        return []

def download_and_display_image(s3_url, fallback_bucket_name):
    """Download image data directly from S3 and display it"""
    try:
        s3_client = boto3.client('s3', region_name='us-west-2')
        
        # Extract bucket and key from S3 URL
        if s3_url.startswith('s3://'):
            path = s3_url.replace('s3://', '')
            parts = path.split('/', 1)
            if len(parts) == 2:
                bucket_from_url = parts[0]
                key = parts[1]
                bucket_to_use = bucket_from_url if bucket_from_url else fallback_bucket_name
            else:
                return None
        else:
            return None
        
        # First check if the object exists
        try:
            s3_client.head_object(Bucket=bucket_to_use, Key=key)
        except Exception:
            # Try URL encoding the key for special characters
            try:
                encoded_key = quote(key, safe='/')
                s3_client.head_object(Bucket=bucket_to_use, Key=encoded_key)
                key = encoded_key  # Use encoded key if it works
            except Exception:
                return None
        
        # Download the image data
        response = s3_client.get_object(Bucket=bucket_to_use, Key=key)
        image_data = response['Body'].read()
        return image_data
        
    except Exception:
        return None

# Removed duplicate display_thumbnails function - using display_images_from_text instead

# Removed old extract_image_urls function - using extract_s3_urls instead

def display_images_from_text(text):
    """Display images found in text and return cleaned text"""
    # Use the updated extract_s3_urls function to get all URLs (including presigned)
    all_urls = extract_s3_urls(text)
    image_urls = [url for url in all_urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif'])]
    
    # Remove duplicates while preserving order
    unique_image_urls = []
    seen_urls = set()
    for url in image_urls:
        # Normalize URL for comparison (remove query parameters)
        normalized_url = url.split('?')[0]
        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            unique_image_urls.append(url)
    
    if unique_image_urls:
        st.markdown("### 📸 Thumbnails:")
        
        # Display images in columns (max 3 per row)
        cols = st.columns(min(len(unique_image_urls), 3))
        for i, url in enumerate(unique_image_urls):
            with cols[i % 3]:
                try:
                    # Extract filename from URL for caption
                    filename = url.split('/')[-1].split('?')[0]  # Remove query parameters
                    if len(filename) > 30:
                        filename = filename[:27] + "..."
                    
                    # Try to display the image - NO fallback links
                    st.image(url, caption=filename, use_container_width=True)
                    
                except Exception as e:
                    # Silent failure - don't show broken links
                    pass
    
    # Aggressively clean up the text by removing URLs and technical details
    cleaned_text = text
    
    # Remove all presigned URLs (both in markdown and standalone)
    for url in image_urls:
        cleaned_text = cleaned_text.replace(url, "")
    
    # Remove markdown links for thumbnails
    markdown_pattern = r'\[([^\]]*(?:thumbnail|view|click|image)[^\]]*)\]\([^)]+\)'
    cleaned_text = re.sub(markdown_pattern, "", cleaned_text, flags=re.IGNORECASE)
    
    # Remove technical details that clutter the response
    technical_patterns = [
        r'Location: thumbnails/[^\n]+',
        r'Size: [\d\.]+ KB',
        r'Status: Successfully completed',
        r'View the thumbnail here:.*',
        r'Click here to view.*',
        r'Click to view.*',
        r'\[Click[^\]]*\]\([^)]+\)',
        r'The thumbnail was extracted using.*',
        r'The thumbnail is now saved.*',
        r'Thumbnail displayed above.*',
        r'✅ Successfully extracted at \d+ seconds.*',
        r'📁 Saved to: `[^`]+`',
        r'📏 Size: [\d\.]+ KB',
        r'🔗 \*\*View thumbnail here:\*\*.*',
        r'View thumbnail:.*',
        r'Both thumbnails.*successfully extracted.*',
        r'The thumbnails are now available.*'
    ]
    
    for pattern in technical_patterns:
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE | re.MULTILINE)
    
    # Clean up extra whitespace and line breaks
    cleaned_text = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_text)  # Remove triple+ line breaks
    cleaned_text = re.sub(r'^\s*\n', '', cleaned_text)  # Remove leading empty lines
    cleaned_text = re.sub(r'\n\s*$', '', cleaned_text)  # Remove trailing empty lines
    
    return cleaned_text.strip()

def format_agent_response(response_text):
    """Format agent response for better display in Streamlit"""
    if not response_text:
        return response_text
    
    # Replace literal \n with actual line breaks
    formatted_text = response_text.replace('\\n', '\n')
    
    # Clean up multiple consecutive line breaks
    formatted_text = re.sub(r'\n{3,}', '\n\n', formatted_text)
    
    # Look for structured sections and format them nicely
    sections = []
    current_section = []
    
    lines = formatted_text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            if current_section:
                current_section.append('')
            continue
            
        # Check if this looks like a section header
        if (line.endswith(':') and len(line) < 100) or \
           (line.startswith('##') or line.startswith('**') or 
            any(keyword in line.lower() for keyword in ['summary', 'overview', 'analysis', 'platform', 'system', 'implementation'])):
            
            # Save previous section
            if current_section:
                sections.append('\n'.join(current_section))
                current_section = []
            
            # Start new section with header
            current_section.append(f"**{line.replace('**', '').replace('##', '').strip()}**")
        else:
            # Add to current section
            current_section.append(line)
    
    # Add final section
    if current_section:
        sections.append('\n'.join(current_section))
    
    return '\n\n'.join(sections) if sections else formatted_text

def parse_agent_response(boto3_response):
    """Parse agent response handling both streaming and non-streaming formats"""
    try:
        if "text/event-stream" in boto3_response.get("contentType", ""):
            # Handle streaming response
            content_parts = []
            for line in boto3_response["response"].iter_lines(chunk_size=1):
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            parsed = json.loads(data)
                            content_parts.append(str(parsed))
                        except:
                            content_parts.append(data)
            return "\n".join(content_parts)
        else:
            # Handle non-streaming response
            events = []
            for event in boto3_response.get("response", []):
                events.append(event)
            
            if events:
                # Combine ALL events, not just the first one
                all_content = []
                for event in events:
                    try:
                        event_text = event.decode("utf-8")
                        try:
                            parsed = json.loads(event_text)
                            all_content.append(str(parsed))
                        except json.JSONDecodeError:
                            all_content.append(event_text)
                    except Exception as e:
                        all_content.append(f"Error decoding event: {e}")
                
                # Join all content parts
                full_response = "\n".join(all_content)
                return full_response
            else:
                return "No response received"
    except Exception as e:
        return f"Error parsing response: {e}"

def invoke_video_agent(agent_arn, prompt):
    """Invoke the video agent with a prompt"""
    try:
        agentcore_client = boto3.client('bedrock-agentcore', region_name='us-west-2')
        
        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            qualifier="DEFAULT",
            payload=json.dumps({"prompt": prompt})
        )
        
        return parse_agent_response(response)
    except Exception as e:
        return f"❌ Error invoking agent: {str(e)}"

# ========================================
# 🔧 CONFIGURATION - UPDATE THESE VALUES
# ========================================
# 1. Deploy your agent: python3 deploy_video_agent.py
# 2. Copy the Agent ARN from the output
# 3. Deploy S3 storage and get bucket name
# 4. Update the values below:

DEFAULT_AGENT_ARN = "arn:aws:bedrock-agentcore:us-west-2:966964893208:runtime/video_agent_final-R7bW1CGSYq"
DEFAULT_BUCKET_NAME = "media-workshop-videos-966964893208-us-west-2"

# ========================================

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'agent_arn' not in st.session_state:
    st.session_state.agent_arn = DEFAULT_AGENT_ARN
if 'bucket_name' not in st.session_state:
    st.session_state.bucket_name = DEFAULT_BUCKET_NAME
if 'quick_action_used' not in st.session_state:
    st.session_state.quick_action_used = False

# Sidebar configuration
st.sidebar.title("🔧 Agent Configuration")

# Agent ARN input
agent_arn = st.sidebar.text_input(
    "Agent ARN",
    value=st.session_state.agent_arn,
    help="Update DEFAULT_AGENT_ARN in the code with your deployed agent ARN",
    placeholder="arn:aws:bedrock-agentcore:us-west-2:..."
)
st.session_state.agent_arn = agent_arn

# Bucket name input
bucket_name = st.sidebar.text_input(
    "S3 Bucket Name",
    value=st.session_state.bucket_name,
    help="Update DEFAULT_BUCKET_NAME in the code with your S3 bucket name",
    placeholder="your-video-bucket-name"
)
st.session_state.bucket_name = bucket_name

# Quick action buttons
st.sidebar.markdown("### 🚀 Quick Actions")

if st.sidebar.button("📋 List Videos"):
    if agent_arn and bucket_name:
        prompt = f"Can you list all the videos in the S3 bucket '{bucket_name}'?"
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.quick_action_used = True
        st.rerun()

if st.sidebar.button("🎬 Analyze First Video"):
    if agent_arn and bucket_name:
        prompt = f"List videos in '{bucket_name}' and analyze the first one with Pegasus AI"
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.quick_action_used = True
        st.rerun()

if st.sidebar.button("👤 Detect Celebrities"):
    if agent_arn and bucket_name:
        prompt = f"Analyze celebrities in the first videos from bucket '{bucket_name}'"
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.quick_action_used = True
        st.rerun()

if st.sidebar.button("📸 Generate Thumbnails"):
    if agent_arn and bucket_name:
        prompt = f"Extract thumbnails from all videos in bucket '{bucket_name} and show them to me'"
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.quick_action_used = True
        st.rerun()

# Removed direct thumbnail view - thumbnails only show when agent mentions them

# Clear chat button
if st.sidebar.button("🗑️ Clear Chat"):
    st.session_state.messages = []
    st.rerun()

# Connection status
st.sidebar.markdown("### 📊 Status")
if agent_arn:
    st.sidebar.success("✅ Agent ARN configured")
else:
    st.sidebar.error("❌ Agent ARN required")

if bucket_name:
    st.sidebar.success("✅ Bucket configured")
else:
    st.sidebar.warning("⚠️ Bucket name recommended")

# Main interface
st.title("🎬 Video Agent Chat Interface")
st.markdown("Chat with your deployed video agent to analyze videos, extract thumbnails, detect faces, and more!")

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            # Display images first, then clean text
            cleaned_content = display_images_from_text(message["content"])
            formatted_content = format_agent_response(cleaned_content)
            st.markdown(formatted_content)
        else:
            # Display user messages as-is
            st.markdown(message["content"])

# Handle Quick Action invocation
if st.session_state.quick_action_used and st.session_state.messages:
    # Get the last message (which should be the Quick Action prompt)
    last_message = st.session_state.messages[-1]
    if last_message["role"] == "user":
        prompt = last_message["content"]
        
        if not agent_arn:
            st.error("❌ Please configure the Agent ARN in the sidebar first!")
        else:
            # Get agent response for Quick Action
            with st.chat_message("assistant"):
                with st.spinner("🤖 Agent is thinking..."):
                    response = invoke_video_agent(agent_arn, prompt)
                
                # Display images first, then clean text
                cleaned_response = display_images_from_text(response)
                formatted_response = format_agent_response(cleaned_response)
                st.markdown(formatted_response)
                
                # Add assistant response to chat history
                st.session_state.messages.append({"role": "assistant", "content": response})
        
        # Reset the flag
        st.session_state.quick_action_used = False

# Chat input
if prompt := st.chat_input("Ask your video agent anything..."):
    if not agent_arn:
        st.error("❌ Please configure the Agent ARN in the sidebar first!")
    else:
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get agent response
        with st.chat_message("assistant"):
            with st.spinner("🤖 Agent is thinking..."):
                response = invoke_video_agent(agent_arn, prompt)
            
            # Display images first, then clean text
            cleaned_response = display_images_from_text(response)
            formatted_response = format_agent_response(cleaned_response)
            st.markdown(formatted_response)
            
            # Add assistant response to chat history (store original for processing)
            st.session_state.messages.append({"role": "assistant", "content": response})