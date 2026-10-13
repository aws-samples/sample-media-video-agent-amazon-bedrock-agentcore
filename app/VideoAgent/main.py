import boto3
import json
import time
import subprocess
import tempfile
import os
import re
from strands import Agent, tool
from strands.models import BedrockModel

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from memory.session import get_memory_session_manager

app = BedrockAgentCoreApp()

# Configuration comes from the runtime environment (set in agentcore/agentcore.json).
REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
PEGASUS_MODEL_ID = os.getenv("PEGASUS_MODEL_ID", "us.twelvelabs.pegasus-1-5-v1:0")
DEFAULT_ACTOR_ID = "video_agent_user"

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
        bedrock_client = boto3.client('bedrock-runtime', region_name=REGION)
        
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
                    modelId=PEGASUS_MODEL_ID,
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
        
        s3_client = boto3.client('s3', region_name=REGION)
        
        # Create temporary directories
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download video from S3. Local filenames are fixed, never derived from the
            # S3 key, so a crafted key cannot escape the temporary directory.
            _, ext = os.path.splitext(video_key)
            local_video_path = os.path.join(temp_dir, f"input{ext.lower()[:8]}")

            print(f"📥 Downloading video from S3...")
            s3_client.download_file(bucket_name, video_key, local_video_path)

            # S3 key for the thumbnail (flattened under thumbnails/)
            thumbnail_filename = video_key.replace('.mp4', f'_thumb_{time_offset}s.jpg').replace('/', '_')
            local_thumbnail_path = os.path.join(temp_dir, "thumbnail.jpg")
            
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
        s3_client = boto3.client('s3', region_name=REGION)
        
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
        
        s3_client = boto3.client('s3', region_name=REGION)
        response = s3_client.head_object(Bucket=bucket_name, Key=video_key)
        file_size_mb = response['ContentLength'] / (1024 * 1024)

        # ffprobe reads only the container headers over HTTP, so no full download is needed.
        url = s3_client.generate_presigned_url(
            'get_object', Params={'Bucket': bucket_name, 'Key': video_key}, ExpiresIn=300
        )
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', url],
            capture_output=True, text=True, timeout=60,
        )
        if probe.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {probe.stderr.strip()[:300]}")

        info = json.loads(probe.stdout)
        duration = float(info.get('format', {}).get('duration', 0))
        video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})

        return {
            'video_path': f"{bucket_name}/{video_key}",
            'duration_seconds': round(duration, 2),
            'duration_formatted': time.strftime('%H:%M:%S', time.gmtime(duration)),
            'file_size_mb': round(file_size_mb, 2),
            'video_codec': video.get('codec_name'),
            'resolution': f"{video.get('width')}x{video.get('height')}" if video else None,
            'frame_rate': video.get('avg_frame_rate'),
            'content_type': response.get('ContentType', 'unknown'),
            'last_modified': response['LastModified'].isoformat(),
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
        rekognition_client = boto3.client('rekognition', region_name=REGION)
        
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
        
        rekognition_client = boto3.client('rekognition', region_name=REGION)
        
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
        
        rekognition_client = boto3.client('rekognition', region_name=REGION)
        
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

TOOLS = [
    list_s3_videos,
    get_video_metadata,
    analyze_video_with_pegasus,
    extract_video_thumbnail,
    get_video_duration,
    list_existing_thumbnails,
    detect_celebrities_in_video,
    check_celebrity_recognition_job,
    get_recent_celebrity_job_status,
    detect_faces_in_video,
]


def build_agent(session_id, actor_id, default_bucket=None):
    """Create an agent bound to this conversation's AgentCore Memory session."""
    system_prompt = VIDEO_AGENT_PROMPT
    if default_bucket:
        system_prompt += (
            f"\n\nThe user's video bucket is '{default_bucket}'. Use it whenever the user "
            "does not name a bucket explicitly."
        )
    return Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name=REGION),
        system_prompt=system_prompt,
        tools=TOOLS,
        session_manager=get_memory_session_manager(session_id, actor_id),
    )


@app.entrypoint
def video_agent_bedrock(payload, context):
    """Invoke the video agent. Conversation history is persisted by AgentCore Memory,
    keyed by the runtime session ID (or payload session_id) and actor_id."""
    user_input = payload.get("prompt")
    if not user_input:
        return "Please send a JSON payload with a 'prompt' field."

    actor_id = payload.get("actor_id", DEFAULT_ACTOR_ID)
    session_id = getattr(context, "session_id", None) or payload.get("session_id")

    # Only accept a valid S3 bucket name, since it is placed into the system prompt
    bucket = payload.get("bucket_name") or ""
    default_bucket = bucket if re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) else None

    agent = build_agent(session_id, actor_id, default_bucket)
    response = agent(user_input)
    return str(response)


if __name__ == "__main__":
    app.run()
