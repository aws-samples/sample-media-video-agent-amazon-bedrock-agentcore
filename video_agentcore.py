import boto3
import json
import time
import subprocess
import tempfile
import os
from strands import Agent, tool
from strands.models import BedrockModel

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient

app = BedrockAgentCoreApp()

# Memory configurationn
MEMORY_CLIENT = None
MEMORY_ID = None
ACTOR_ID = "video_agent_user"  # Default actor ID
SESSION_ID = "video_session_001"  # Default session ID

def initialize_memory():
    """Initialize or retrieve existing memory for the video agent"""
    global MEMORY_CLIENT, MEMORY_ID
    
    try:
        print("🧠 Initializing video agent memory...")
        MEMORY_CLIENT = MemoryClient(region_name="us-west-2")
        print(f"🧠 Created memory client: {MEMORY_CLIENT}")
        memory_name = "VideoAgentMemory"
        print(f"🧠 Looking for memory with name: {memory_name}")
        
        # Try to find existing memory first
        print(f"🧠 Listing existing memories...")
        memories = MEMORY_CLIENT.list_memories()
        print(f"🧠 Found {len(memories)} memories: {memories}")
        
        existing_memory = None
        for memory in memories:
            memory_id_in_list = memory.get('id', '')
            print(f"🧠 Checking memory: id='{memory_id_in_list}', looking for='{memory_name}'")
            if memory_id_in_list.startswith(memory_name):
                existing_memory = memory
                print(f"🧠 Found matching memory: {memory}")
                break
            else:
                print(f"🧠 No match: '{memory_id_in_list}' does not start with '{memory_name}'")
        
        if existing_memory:
            MEMORY_ID = existing_memory['id']
            print(f"✅ Using existing memory: {MEMORY_ID}")
        else:
            # Create new memory resource for short-term memory
            memory = MEMORY_CLIENT.create_memory(
                name=memory_name,
                description="Short-term memory for video agent conversations"
            )
            MEMORY_ID = memory['id']
            print(f"✅ Created new memory: {MEMORY_ID}")
            
    except Exception as e:
        print(f"⚠️ Memory initialization failed: {e}")
        print("📝 Agent will continue without memory functionality")

def load_conversation_history(actor_id: str = None, session_id: str = None):
    """Load recent conversation history from memory"""
    global MEMORY_CLIENT, MEMORY_ID
    
    print(f"🧠 load_conversation_history called with actor_id={actor_id}, session_id={session_id}")
    print(f"🧠 MEMORY_CLIENT exists: {MEMORY_CLIENT is not None}")
    print(f"🧠 MEMORY_ID: {MEMORY_ID}")
    
    if not MEMORY_CLIENT or not MEMORY_ID:
        print("🧠 No memory client or ID available - returning empty history")
        return ""
    
    try:
        # Use provided IDs or defaults
        actor = actor_id or ACTOR_ID
        session = session_id or SESSION_ID
        
        print(f"🧠 Calling get_last_k_turns with memory_id={MEMORY_ID}, actor_id={actor}, session_id={session}")
        
        # Get last 5 conversation turns
        recent_turns = MEMORY_CLIENT.get_last_k_turns(
            memory_id=MEMORY_ID,
            actor_id=actor,
            session_id=session,
            k=5
        )
        
        print(f"🧠 get_last_k_turns returned: {recent_turns}")
        
        if not recent_turns:
            print("🧠 No recent turns found")
            return ""
        
        # Format conversation history
        context_messages = []
        for turn in recent_turns:
            for message in turn:
                role = message['role']
                content = message['content']['text']
                context_messages.append(f"{role}: {content}")
        
        context = "\n".join(context_messages)
        print(f"🧠 Loaded {len(recent_turns)} conversation turns from memory")
        print(f"🧠 Context preview: {context[:200]}...")
        return f"\n\nRecent conversation history:\n{context}\n"
        
    except Exception as e:
        print(f"⚠️ Failed to load conversation history: {e}")
        import traceback
        print(f"⚠️ Full traceback: {traceback.format_exc()}")
        return ""

def store_interaction(user_message: str, assistant_response: str, actor_id: str = None, session_id: str = None):
    """Store user interaction in memory"""
    global MEMORY_CLIENT, MEMORY_ID
    
    print(f"🧠 store_interaction called with actor_id={actor_id}, session_id={session_id}")
    print(f"🧠 User message length: {len(user_message)}")
    print(f"🧠 Assistant response length: {len(assistant_response)}")
    
    if not MEMORY_CLIENT or not MEMORY_ID:
        print("🧠 No memory client or ID available - skipping storage")
        return
    
    try:
        # Use provided IDs or defaults
        actor = actor_id or ACTOR_ID
        session = session_id or SESSION_ID
        
        print(f"🧠 Calling create_event with memory_id={MEMORY_ID}, actor_id={actor}, session_id={session}")
        
        # Store the conversation turn
        result = MEMORY_CLIENT.create_event(
            memory_id=MEMORY_ID,
            actor_id=actor,
            session_id=session,
            messages=[
                (user_message, "USER"),
                (assistant_response, "ASSISTANT")
            ]
        )
        print(f"🧠 Stored interaction in memory successfully: {result}")
        
    except Exception as e:
        print(f"⚠️ Failed to store interaction: {e}")
        import traceback
        print(f"⚠️ Full traceback: {traceback.format_exc()}")

# Define a video-focused system prompt
VIDEO_AGENT_PROMPT = """You are a video library assistant that helps users manage and explore their video collection stored in Amazon S3.

You can help users:
- List videos in their S3 bucket
- Find specific videos by name or type
- Get information about video files including metadata
- Browse videos by category or folder
- Analyze video content using AI to provide summaries and insights
- Extract thumbnail images from videos
- Get video duration and technical specifications
- Detect faces and people in videos
- Recognize celebrities and famous people with timestamps

IMPORTANT: Celebrity detection is an ASYNC process:
- When users ask to detect celebrities, use detect_celebrities_in_video() which starts the job and returns immediately
- Always explain that celebrity detection takes 5-10 minutes and provide the job ID
- When users ask to check status, use check_celebrity_recognition_job() with the job ID
- Remember job IDs from previous conversations to help users check their jobs

Use the available tools to provide helpful information about the video library.
Always provide friendly and informative responses about the video collection.
"""

@tool
def list_s3_videos(bucket_name: str, prefix: str = "") -> dict:
    """List video files in an S3 bucket.

    Args:
        bucket_name: The name of the S3 bucket
        prefix: Optional prefix to filter results (e.g., 'movies/' or 'tv-shows/')
    """
    try:
        print(f"Attempting to list objects in bucket: {bucket_name}, prefix: {prefix}")
        s3_client = boto3.client('s3')
        
        # First check if bucket exists
        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except Exception as bucket_error:
            return {
                'error': f"Cannot access bucket '{bucket_name}': {str(bucket_error)}",
                'bucket': bucket_name,
                'prefix': prefix,
                'suggestion': "Please check if the bucket exists and you have permissions to access it."
            }
        
        # List objects in the bucket
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            MaxKeys=50  # Limit results
        )
        
        videos = []
        all_objects = []
        
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                all_objects.append(key)
                
                # Filter for video files (basic check by extension)
                if key.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv')):
                    video_info = {
                        'name': key.split('/')[-1],  # Just the filename
                        'full_path': key,
                        'size_bytes': obj['Size'],
                        'size_mb': round(obj['Size'] / (1024 * 1024), 2) if obj['Size'] > 0 else 0,
                        'last_modified': obj['LastModified'].isoformat(),
                        'folder': '/'.join(key.split('/')[:-1]) if '/' in key else 'root'
                    }
                    videos.append(video_info)
        
        return {
            'bucket': bucket_name,
            'prefix': prefix or 'root',
            'total_objects': len(all_objects),
            'total_videos': len(videos),
            'videos': videos,
            'all_objects': all_objects[:10]  # Show first 10 objects for debugging
        }
        
    except Exception as e:
        print(f"Error in list_s3_videos: {str(e)}")
        return {
            'error': f"Failed to list videos: {str(e)}",
            'bucket': bucket_name,
            'prefix': prefix,
            'error_type': type(e).__name__
        }

@tool
def analyze_video_with_pegasus(bucket_name: str, video_key: str, prompt: str = "Analyze this video and provide a summary") -> dict:
    """Analyze a video using Amazon Bedrock's TwelveLabs Pegasus model.

    Args:
        bucket_name: The name of the S3 bucket containing the video
        video_key: The S3 key/path to the video file
        prompt: The analysis prompt for the model (default: general summary)
    """
    try:
        print(f"🎬 Analyzing video with Pegasus: {bucket_name}/{video_key}")
        
        # Get AWS account ID for bucket owner
        sts_client = boto3.client('sts')
        account_id = sts_client.get_caller_identity()['Account']
        
        # Create Bedrock client
        bedrock_client = boto3.client('bedrock-runtime', region_name='us-west-2')
        
        # Prepare the request payload
        request_payload = {
            "inputPrompt": prompt,
            "mediaSource": {
                "s3Location": {
                    "uri": f"s3://{bucket_name}/{video_key}",
                    "bucketOwner": account_id
                }
            },
            "temperature": 0.2,
            "maxOutputTokens": 4096
        }
        
        # Call Pegasus model with retry logic for throttling
        import time
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = bedrock_client.invoke_model(
                    modelId="us.twelvelabs.pegasus-1-2-v1:0",
                    body=json.dumps(request_payload),
                    contentType="application/json"
                )
                break  # Success, exit retry loop
            except Exception as e:
                if "throttling" in str(e).lower() or "rate" in str(e).lower():
                    if attempt < max_retries - 1:
                        print(f"⏳ Throttling detected, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                raise e  # Re-raise if not throttling or max retries reached
        
        # Parse response
        response_body = json.loads(response['body'].read())
        
        return {
            'video_path': f"{bucket_name}/{video_key}",
            'analysis_prompt': prompt,
            'summary': response_body.get('message', 'No analysis returned'),
            'finish_reason': response_body.get('finishReason', 'unknown'),
            'success': True
        }
        
    except Exception as e:
        print(f"❌ Error analyzing video with Pegasus: {str(e)}")
        return {
            'error': f"Failed to analyze video: {str(e)}",
            'video_path': f"{bucket_name}/{video_key}",
            'analysis_prompt': prompt,
            'success': False,
            'error_type': type(e).__name__
        }

@tool
def extract_video_thumbnail(bucket_name: str, video_key: str, time_offset: int = 10) -> dict:
    """Extract a thumbnail image from a video using ffmpeg.

    Args:
        bucket_name: The name of the S3 bucket containing the video
        video_key: The S3 key/path to the video file
        time_offset: Time in seconds to extract thumbnail from (default: 10)
    """
    try:
        print(f"📸 Starting ffmpeg thumbnail extraction: {bucket_name}/{video_key} at {time_offset}s")
        
        s3_client = boto3.client('s3', region_name='us-west-2')
        
        # Create temporary directories
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download video from S3
            video_filename = os.path.basename(video_key)
            local_video_path = os.path.join(temp_dir, video_filename)
            
            print(f"📥 Downloading video from S3...")
            s3_client.download_file(bucket_name, video_key, local_video_path)
            
            # Create thumbnail filename
            thumbnail_filename = video_key.replace('.mp4', f'_thumb_{time_offset}s.jpg').replace('/', '_')
            local_thumbnail_path = os.path.join(temp_dir, thumbnail_filename)
            
            # Use ffmpeg to extract thumbnail
            print(f"🎬 Extracting thumbnail with ffmpeg...")
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', local_video_path,
                '-ss', str(time_offset),  # Seek to time_offset seconds
                '-vframes', '1',  # Extract only 1 frame
                '-q:v', '2',  # High quality (1-31, lower is better)
                '-y',  # Overwrite output file
                local_thumbnail_path
            ]
            
            # Run ffmpeg command
            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
            )
            
            if result.returncode != 0:
                print(f"❌ ffmpeg failed: {result.stderr}")
                return {
                    'video_path': f"{bucket_name}/{video_key}",
                    'thumbnail_extracted': False,
                    'time_offset': time_offset,
                    'error': f"ffmpeg failed: {result.stderr}",
                    'message': 'Thumbnail extraction failed - ffmpeg error',
                    'success': False
                }
            
            # Check if thumbnail was created
            if not os.path.exists(local_thumbnail_path):
                return {
                    'video_path': f"{bucket_name}/{video_key}",
                    'thumbnail_extracted': False,
                    'time_offset': time_offset,
                    'error': 'Thumbnail file not created',
                    'message': 'Thumbnail extraction failed - no output file',
                    'success': False
                }
            
            # Upload thumbnail to S3
            thumbnail_key = f"thumbnails/{thumbnail_filename}"
            print(f"📤 Uploading thumbnail to S3: {thumbnail_key}")
            
            s3_client.upload_file(
                local_thumbnail_path,
                bucket_name,
                thumbnail_key,
                ExtraArgs={'ContentType': 'image/jpeg'}
            )
            
            # Get thumbnail file size
            thumbnail_size = os.path.getsize(local_thumbnail_path)
            
            print(f"✅ Thumbnail extraction completed successfully!")
            
            # Generate presigned URL for immediate viewing
            try:
                presigned_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket_name, 'Key': thumbnail_key},
                    ExpiresIn=3600  # 1 hour expiration
                )
                print(f"✅ Generated presigned URL: {presigned_url[:100]}...")
                thumbnail_display_url = presigned_url
            except Exception as e:
                print(f"❌ Failed to generate presigned URL: {e}")
                thumbnail_display_url = f"s3://{bucket_name}/{thumbnail_key}"
            
            return {
                'video_path': f"{bucket_name}/{video_key}",
                'thumbnail_extracted': True,
                'time_offset': time_offset,
                'thumbnail_location': thumbnail_key,
                'thumbnail_url': thumbnail_display_url,
                'thumbnail_size_bytes': thumbnail_size,
                'thumbnail_size_kb': round(thumbnail_size / 1024, 2),
                'method': 'ffmpeg',
                'message': f"Thumbnail successfully extracted at {time_offset}s and saved to {thumbnail_key}. View at: {thumbnail_display_url}",
                'processing_status': 'COMPLETED',
                'success': True
            }
            
    except subprocess.TimeoutExpired:
        print(f"⏰ ffmpeg timeout after 60 seconds")
        return {
            'video_path': f"{bucket_name}/{video_key}",
            'thumbnail_extracted': False,
            'time_offset': time_offset,
            'error': 'ffmpeg timeout after 60 seconds',
            'message': 'Thumbnail extraction timed out',
            'success': False
        }
        
    except FileNotFoundError:
        print(f"❌ ffmpeg not found - falling back to simulated thumbnail")
        # Graceful fallback for environments without ffmpeg
        thumbnail_key = f"thumbnails/{video_key.replace('.mp4', f'_thumb_{time_offset}s.jpg').replace('/', '_')}"
        return {
            'video_path': f"{bucket_name}/{video_key}",
            'thumbnail_extracted': True,
            'time_offset': time_offset,
            'thumbnail_location': thumbnail_key,
            'thumbnail_url': f"s3://{bucket_name}/{thumbnail_key}",
            'method': 'simulated',
            'message': f"Thumbnail extraction simulated at {time_offset}s (ffmpeg not available)",
            'note': 'This is a fallback response - actual thumbnail not generated',
            'processing_status': 'SIMULATED',
            'success': True
        }
        
    except Exception as e:
        print(f"❌ Error extracting thumbnail: {str(e)}")
        return {
            'error': f"Failed to extract thumbnail: {str(e)}",
            'video_path': f"{bucket_name}/{video_key}",
            'message': 'Thumbnail extraction failed',
            'suggestion': 'Check video file format and ffmpeg installation',
            'success': False,
            'error_type': type(e).__name__
        }

@tool
def list_existing_thumbnails(bucket_name: str) -> dict:
    """List all existing thumbnail images with ready-to-view URLs.
    
    Args:
        bucket_name: The S3 bucket containing thumbnails
    """
    try:
        print(f"📸 Listing existing thumbnails in: {bucket_name}")
        s3_client = boto3.client('s3', region_name='us-west-2')
        
        # List objects in thumbnails folder
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix='thumbnails/',
            MaxKeys=50
        )
        
        thumbnails = []
        for obj in response.get('Contents', []):
            key = obj['Key']
            if any(ext in key.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                # Generate presigned URL for each thumbnail
                try:
                    presigned_url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket_name, 'Key': key},
                        ExpiresIn=3600  # 1 hour expiration
                    )
                    print(f"✅ Generated presigned URL for {key}: {presigned_url[:100]}...")
                    
                    thumbnails.append({
                        'filename': key.split('/')[-1],
                        'key': key,
                        'url': presigned_url,
                        'size_bytes': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat()
                    })
                except Exception:
                    # Skip thumbnails we can't generate URLs for
                    continue
        
        if thumbnails:
            thumbnail_list = "\n".join([
                f"• {thumb['filename']}: {thumb['url']}" 
                for thumb in thumbnails
            ])
            
            return {
                'bucket': bucket_name,
                'total_thumbnails': len(thumbnails),
                'thumbnails': thumbnails,
                'message': f"Found {len(thumbnails)} thumbnail images with ready-to-view URLs:\n\n{thumbnail_list}",
                'success': True
            }
        else:
            return {
                'bucket': bucket_name,
                'total_thumbnails': 0,
                'thumbnails': [],
                'message': 'No thumbnail images found in the bucket',
                'success': True
            }
            
    except Exception as e:
        print(f"❌ Error listing thumbnails: {str(e)}")
        return {
            'error': f"Failed to list thumbnails: {str(e)}",
            'bucket': bucket_name,
            'message': 'Could not access thumbnail folder',
            'success': False,
            'error_type': type(e).__name__
        }

@tool
def get_video_duration(bucket_name: str, video_key: str) -> dict:
    """Get technical metadata including duration for a video file.

    Args:
        bucket_name: The name of the S3 bucket containing the video
        video_key: The S3 key/path to the video file
    """
    try:
        print(f"⏱️ Getting video duration for: {bucket_name}/{video_key}")
        
        # Get basic S3 metadata first
        s3_client = boto3.client('s3')
        response = s3_client.head_object(Bucket=bucket_name, Key=video_key)
        
        # For now, estimate duration based on file size (rough approximation)
        # In a full implementation, this would use AWS MediaInfo or similar service
        file_size_mb = response['ContentLength'] / (1024 * 1024)
        estimated_duration_minutes = max(1, int(file_size_mb / 10))  # Rough estimate
        
        return {
            'video_path': f"{bucket_name}/{video_key}",
            'file_size_mb': round(file_size_mb, 2),
            'estimated_duration_minutes': estimated_duration_minutes,
            'estimated_duration_seconds': estimated_duration_minutes * 60,
            'content_type': response.get('ContentType', 'unknown'),
            'last_modified': response['LastModified'].isoformat(),
            'note': "Duration is estimated - full implementation would use AWS MediaInfo",
            'success': True
        }
        
    except Exception as e:
        print(f"❌ Error getting video duration: {str(e)}")
        return {
            'error': f"Failed to get video duration: {str(e)}",
            'video_path': f"{bucket_name}/{video_key}",
            'success': False,
            'error_type': type(e).__name__
        }

@tool
def detect_faces_in_video(bucket_name: str, video_key: str, wait_for_completion: bool = True) -> dict:
    """Detect faces in a video using Amazon Rekognition with real-time polling.

    Args:
        bucket_name: The name of the S3 bucket containing the video
        video_key: The S3 key/path to the video file
        wait_for_completion: Whether to wait for job completion (default: True)
    """
    try:
        print(f"👤 Starting face detection for: {bucket_name}/{video_key}")
        
        # Create Rekognition client
        rekognition_client = boto3.client('rekognition', region_name='us-west-2')
        
        # Start face detection job
        response = rekognition_client.start_face_detection(
            Video={
                'S3Object': {
                    'Bucket': bucket_name,
                    'Name': video_key
                }
            }
        )
        
        job_id = response['JobId']
        print(f"🔄 Rekognition job started: {job_id}")
        
        if not wait_for_completion:
            return {
                'video_path': f"{bucket_name}/{video_key}",
                'rekognition_job_id': job_id,
                'status': 'IN_PROGRESS',
                'message': 'Face detection job started - call again to check status',
                'success': True
            }
        
        # Poll for completion with user feedback
        import time
        max_wait_time = 600  # 10 minutes max
        poll_interval = 10   # Check every 10 seconds
        elapsed_time = 0
        
        print("⏳ Waiting for face detection to complete...")
        
        while elapsed_time < max_wait_time:
            try:
                # Check job status
                job_response = rekognition_client.get_face_detection(JobId=job_id)
                status = job_response['JobStatus']
                
                if status == 'SUCCEEDED':
                    print("✅ Face detection completed successfully!")
                    
                    # Process the results
                    faces = job_response.get('Faces', [])
                    
                    # Analyze face detection results
                    face_analysis = analyze_face_results(faces)
                    
                    return {
                        'video_path': f"{bucket_name}/{video_key}",
                        'rekognition_job_id': job_id,
                        'status': 'SUCCEEDED',
                        'total_faces_detected': len(faces),
                        'analysis': face_analysis,
                        'processing_time_seconds': elapsed_time,
                        'success': True
                    }
                    
                elif status == 'FAILED':
                    error_msg = job_response.get('StatusMessage', 'Unknown error')
                    print(f"❌ Face detection failed: {error_msg}")
                    return {
                        'video_path': f"{bucket_name}/{video_key}",
                        'rekognition_job_id': job_id,
                        'status': 'FAILED',
                        'error': f"Rekognition job failed: {error_msg}",
                        'processing_time_seconds': elapsed_time,
                        'success': False
                    }
                    
                elif status == 'IN_PROGRESS':
                    print(f"⏳ Still processing... ({elapsed_time}s elapsed)")
                    time.sleep(poll_interval)
                    elapsed_time += poll_interval
                    
            except Exception as poll_error:
                print(f"⚠️ Error checking job status: {poll_error}")
                time.sleep(poll_interval)
                elapsed_time += poll_interval
        
        # Timeout reached
        print(f"⏰ Timeout reached after {max_wait_time} seconds")
        return {
            'video_path': f"{bucket_name}/{video_key}",
            'rekognition_job_id': job_id,
            'status': 'TIMEOUT',
            'message': f'Job is still processing after {max_wait_time} seconds',
            'suggestion': 'Check job status later or increase timeout',
            'processing_time_seconds': elapsed_time,
            'success': False
        }
        
    except Exception as e:
        print(f"❌ Error detecting faces: {str(e)}")
        return {
            'error': f"Face detection failed: {str(e)}",
            'video_path': f"{bucket_name}/{video_key}",
            'message': 'Face detection requires Amazon Rekognition permissions',
            'suggestion': 'Ensure IAM role has rekognition:* permissions',
            'success': False,
            'error_type': type(e).__name__
        }

def analyze_face_results(faces):
    """Analyze face detection results and provide insights."""
    if not faces:
        return {
            'summary': 'No faces detected in the video',
            'details': []
        }
    
    # Group faces by timestamp ranges
    face_timeline = {}
    confidence_scores = []
    
    for face_data in faces:
        timestamp = face_data.get('Timestamp', 0)
        face = face_data.get('Face', {})
        confidence = face.get('Confidence', 0)
        confidence_scores.append(confidence)
        
        # Group by 10-second intervals
        time_bucket = (timestamp // 10000) * 10  # Convert to seconds and bucket
        
        if time_bucket not in face_timeline:
            face_timeline[time_bucket] = []
        
        face_timeline[time_bucket].append({
            'timestamp': timestamp / 1000,  # Convert to seconds
            'confidence': confidence,
            'bounding_box': face.get('BoundingBox', {}),
            'emotions': face.get('Emotions', []) if 'Emotions' in face else None
        })
    
    # Calculate statistics
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
    max_confidence = max(confidence_scores) if confidence_scores else 0
    
    # Create timeline summary
    timeline_summary = []
    for time_bucket in sorted(face_timeline.keys()):
        faces_in_bucket = face_timeline[time_bucket]
        timeline_summary.append({
            'time_range': f"{time_bucket}-{time_bucket + 10}s",
            'face_count': len(faces_in_bucket),
            'avg_confidence': sum(f['confidence'] for f in faces_in_bucket) / len(faces_in_bucket)
        })
    
    return {
        'summary': f"Detected {len(faces)} face instances across {len(timeline_summary)} time segments",
        'statistics': {
            'total_detections': len(faces),
            'average_confidence': round(avg_confidence, 2),
            'max_confidence': round(max_confidence, 2),
            'time_segments_with_faces': len(timeline_summary)
        },
        'timeline': timeline_summary[:10],  # Limit to first 10 segments
        'details': f"Faces appear throughout {len(timeline_summary)} different time segments of the video"
    }

@tool
def get_video_metadata(bucket_name: str, video_key: str) -> dict:
    """Get detailed metadata for a specific video file.

    Args:
        bucket_name: The name of the S3 bucket
        video_key: The full S3 key/path to the video file
    """
    try:
        print(f"Getting metadata for: {bucket_name}/{video_key}")
        s3_client = boto3.client('s3')
        
        # Get object metadata
        response = s3_client.head_object(
            Bucket=bucket_name,
            Key=video_key
        )
        
        metadata = {
            'name': video_key.split('/')[-1],
            'full_path': video_key,
            'size_bytes': response['ContentLength'],
            'size_mb': round(response['ContentLength'] / (1024 * 1024), 2) if response['ContentLength'] > 0 else 0,
            'last_modified': response['LastModified'].isoformat(),
            'content_type': response.get('ContentType', 'unknown'),
            'custom_metadata': response.get('Metadata', {})
        }
        
        return metadata
        
    except Exception as e:
        print(f"Error in get_video_metadata: {str(e)}")
        return {
            'error': f"Failed to get video metadata: {str(e)}",
            'video_key': video_key,
            'bucket': bucket_name,
            'error_type': type(e).__name__
        }

@tool
def detect_celebrities_in_video(bucket_name: str, video_key: str) -> dict:
    """Start celebrity detection in a video using Amazon Rekognition (non-blocking).
    
    This tool starts the celebrity recognition job and returns immediately with a job ID.
    Use check_celebrity_recognition_job() to check the status and get results when complete.
    
    Args:
        bucket_name: The S3 bucket containing the video
        video_key: The S3 key (path) to the video file
    """
    try:
        print(f"🌟 Starting celebrity detection for: {bucket_name}/{video_key}")
        
        rekognition_client = boto3.client('rekognition', region_name='us-west-2')
        
        # Start celebrity recognition job
        response = rekognition_client.start_celebrity_recognition(
            Video={
                'S3Object': {
                    'Bucket': bucket_name,
                    'Name': video_key
                }
            }
        )
        
        job_id = response['JobId']
        print(f"🎬 Celebrity recognition job started: {job_id}")
        
        return {
            'video_path': f"{bucket_name}/{video_key}",
            'rekognition_job_id': job_id,
            'status': 'STARTED',
            'message': f'Celebrity detection job started successfully! Job ID: {job_id}',
            'instructions': 'The job is now processing in the background. This typically takes 5-10 minutes depending on video length. Ask me to check the status anytime by saying "check celebrity job status" or similar.',
            'estimated_completion': '5-10 minutes',
            'success': True
        }
        
    except Exception as e:
        print(f"❌ Error detecting celebrities: {str(e)}")
        return {
            'error': f"Celebrity detection failed: {str(e)}",
            'video_path': f"{bucket_name}/{video_key}",
            'message': 'Celebrity detection requires Amazon Rekognition permissions',
            'suggestion': 'Ensure IAM role has rekognition:* permissions',
            'success': False,
            'error_type': type(e).__name__
        }

def analyze_celebrity_results(celebrities):
    """Analyze celebrity recognition results and provide insights with timestamps."""
    if not celebrities:
        return {
            'summary': 'No celebrities detected in the video',
            'details': [],
            'timeline': []
        }
    
    # Group celebrities by name and collect timestamps
    celebrity_appearances = {}
    confidence_scores = []
    
    for celebrity_data in celebrities:
        timestamp = celebrity_data.get('Timestamp', 0)
        celebrity = celebrity_data.get('Celebrity', {})
        
        name = celebrity.get('Name', 'Unknown')
        confidence = celebrity.get('Confidence', 0)
        face = celebrity.get('Face', {})
        face_confidence = face.get('Confidence', 0)
        
        confidence_scores.append(confidence)
        
        if name not in celebrity_appearances:
            celebrity_appearances[name] = {
                'name': name,
                'appearances': [],
                'total_appearances': 0,
                'avg_confidence': 0,
                'first_appearance': timestamp / 1000,
                'last_appearance': timestamp / 1000,
                'urls': celebrity.get('Urls', [])
            }
        
        celebrity_appearances[name]['appearances'].append({
            'timestamp_seconds': timestamp / 1000,
            'timestamp_formatted': format_timestamp(timestamp / 1000),
            'confidence': confidence,
            'face_confidence': face_confidence,
            'bounding_box': face.get('BoundingBox', {})
        })
        
        celebrity_appearances[name]['total_appearances'] += 1
        celebrity_appearances[name]['last_appearance'] = timestamp / 1000
    
    # Calculate averages and create timeline
    timeline = []
    celebrity_list = []
    
    for name, data in celebrity_appearances.items():
        # Calculate average confidence
        avg_confidence = sum(app['confidence'] for app in data['appearances']) / len(data['appearances'])
        data['avg_confidence'] = round(avg_confidence, 2)
        
        celebrity_list.append(data)
        
        # Add to timeline
        for appearance in data['appearances']:
            timeline.append({
                'celebrity': name,
                'timestamp': appearance['timestamp_seconds'],
                'timestamp_formatted': appearance['timestamp_formatted'],
                'confidence': appearance['confidence']
            })
    
    # Sort timeline by timestamp
    timeline.sort(key=lambda x: x['timestamp'])
    
    # Sort celebrities by total appearances
    celebrity_list.sort(key=lambda x: x['total_appearances'], reverse=True)
    
    avg_confidence = round(sum(confidence_scores) / len(confidence_scores), 2) if confidence_scores else 0
    
    return {
        'summary': f"Detected {len(celebrity_appearances)} unique celebrities in {len(celebrities)} total appearances",
        'celebrities': celebrity_list,
        'timeline': timeline,
        'statistics': {
            'unique_celebrities': len(celebrity_appearances),
            'total_appearances': len(celebrities),
            'average_confidence': avg_confidence,
            'video_duration_analyzed': max([c['last_appearance'] for c in celebrity_list]) if celebrity_list else 0
        }
    }

def format_timestamp(seconds):
    """Format seconds into MM:SS or HH:MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

@tool
def get_recent_celebrity_job_status() -> dict:
    """Check the status of the most recent celebrity recognition job from this conversation.
    
    This tool automatically finds the most recent celebrity job ID from the conversation history.
    """
    try:
        print("🔍 Looking for recent celebrity job in conversation history...")
        
        # This is a simplified version - the agent's memory context will contain job IDs
        # The agent can extract job IDs from its conversation history
        return {
            'status': 'INFO',
            'message': 'Please provide the job ID from when you started celebrity detection, or use check_celebrity_recognition_job() with the specific job ID.',
            'suggestion': 'Look for a message like "Job ID: abc123" from when you started celebrity detection.',
            'success': True
        }
        
    except Exception as e:
        return {
            'error': f"Failed to search conversation history: {str(e)}",
            'success': False
        }

@tool
def check_celebrity_recognition_job(job_id: str = None) -> dict:
    """Check the status of a celebrity recognition job.
    
    Args:
        job_id: Optional Rekognition job ID. If not provided, will look for the most recent job ID from conversation history.
    """
    try:
        # If no job_id provided, try to find one from conversation history
        if not job_id:
            print("🔍 No job ID provided, searching conversation history...")
            # This is a simple approach - in a real implementation, you might want to 
            # store job IDs more systematically in memory
            job_id = "MEMORY_LOOKUP_NEEDED"
            return {
                'status': 'ERROR',
                'error': 'No job ID provided. Please provide the job ID from when you started celebrity detection, or start a new celebrity detection job.',
                'suggestion': 'Say something like "check job abc123" or start a new celebrity detection.',
                'success': False
            }
        
        print(f"🔍 Checking celebrity recognition job: {job_id}")
        
        rekognition_client = boto3.client('rekognition', region_name='us-west-2')
        
        # Check job status
        job_response = rekognition_client.get_celebrity_recognition(JobId=job_id)
        status = job_response['JobStatus']
        
        if status == 'SUCCEEDED':
            print("✅ Celebrity recognition completed!")
            
            # Process the results
            celebrities = job_response.get('Celebrities', [])
            celebrity_analysis = analyze_celebrity_results(celebrities)
            
            return {
                'rekognition_job_id': job_id,
                'status': 'SUCCEEDED',
                'total_celebrities_detected': len(celebrities),
                'analysis': celebrity_analysis,
                'success': True
            }
            
        elif status == 'FAILED':
            error_msg = job_response.get('StatusMessage', 'Unknown error')
            print(f"❌ Celebrity recognition failed: {error_msg}")
            return {
                'rekognition_job_id': job_id,
                'status': 'FAILED',
                'error': f"Rekognition job failed: {error_msg}",
                'success': False
            }
            
        elif status == 'IN_PROGRESS':
            print(f"⏳ Job is still processing...")
            return {
                'rekognition_job_id': job_id,
                'status': 'IN_PROGRESS',
                'message': 'Job is still processing. Check again later.',
                'success': False
            }
        
        else:
            return {
                'rekognition_job_id': job_id,
                'status': status,
                'message': f'Job status: {status}',
                'success': False
            }
            
    except Exception as e:
        print(f"❌ Error checking job status: {str(e)}")
        return {
            'error': f"Failed to check job status: {str(e)}",
            'rekognition_job_id': job_id,
            'success': False
        }

# Create a BedrockModel
bedrock_model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    region_name="us-west-2"
)

video_agent = Agent(
    model=bedrock_model,
    system_prompt=VIDEO_AGENT_PROMPT,
    tools=[
        list_s3_videos, 
        get_video_metadata, 
        analyze_video_with_pegasus,
        extract_video_thumbnail,
        get_video_duration,
        list_existing_thumbnails,
        detect_celebrities_in_video,
        check_celebrity_recognition_job,
        get_recent_celebrity_job_status,
        detect_faces_in_video
    ],
)

@app.entrypoint
def video_agent_bedrock(payload):
    """
    Invoke the video agent with a payload, enhanced with memory
    """
    print(f"🚀 Starting video_agent_bedrock with payload: {payload}")
    
    # Initialize memory on first run
    if MEMORY_CLIENT is None:
        print("🧠 Initializing memory for the first time...")
        initialize_memory()
        print(f"🧠 Memory initialization complete. MEMORY_CLIENT: {MEMORY_CLIENT is not None}, MEMORY_ID: {MEMORY_ID}")
    
    # Extract user input and session info
    user_input = payload.get("prompt")
    actor_id = payload.get("actor_id", ACTOR_ID)
    session_id = payload.get("session_id", SESSION_ID)
    
    print(f"🎬 User input: {user_input}")
    print(f"🧠 Session: {actor_id}/{session_id}")
    print(f"🧠 Memory status - Client: {MEMORY_CLIENT is not None}, ID: {MEMORY_ID}")
    
    # Load conversation history and enhance user input with context
    print("🧠 Loading conversation history...")
    conversation_history = load_conversation_history(actor_id, session_id)
    print(f"🧠 Conversation history loaded: {len(conversation_history)} characters")
    
    # Create enhanced prompt with memory context
    if conversation_history:
        enhanced_prompt = f"{conversation_history}\n\nCurrent user message: {user_input}"
        print("🧠 Enhanced prompt with conversation history")
        print(f"🧠 Enhanced prompt preview: {enhanced_prompt[:200]}...")
    else:
        enhanced_prompt = user_input
        print("📝 No previous conversation history found - using original prompt")
    
    # Get response from agent
    print("🤖 Calling video agent...")
    response = video_agent(enhanced_prompt)
    assistant_response = response.message['content'][0]['text']
    print(f"🤖 Agent response received: {len(assistant_response)} characters")
    
    # Store the interaction in memory
    print("🧠 Storing interaction in memory...")
    store_interaction(user_input, assistant_response, actor_id, session_id)
    print("🧠 Memory storage complete")
    
    print(f"🤖 Assistant response: {assistant_response[:100]}...")
    return assistant_response

if __name__ == "__main__":
    app.run()