#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯云语音识别批量转写工具
利用腾讯云每日免费额度，智能分批处理大量音频文件

GitHub: https://github.com/twischen-dot/tencent-asr-batch

使用方法：
  python3 tencent_asr_batch.py --input ./audio --output ./transcripts
  python3 tencent_asr_batch.py --status
"""
import os
import sys
import json
import time
import base64
import hmac
import hashlib
import subprocess
import shutil
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("正在安装 requests...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

# === 从环境变量读取配置 ===
def get_config():
    """获取配置，延迟检查以便显示帮助信息"""
    secret_id = os.getenv("TENCENT_SECRET_ID")
    secret_key = os.getenv("TENCENT_SECRET_KEY")
    region = os.getenv("TENCENT_REGION", "ap-shanghai")
    
    if not secret_id or not secret_key:
        return None, None, region
    return secret_id, secret_key, region

SECRET_ID, SECRET_KEY, REGION = get_config()

# === 支持的音频格式 ===
SUPPORTED = {".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg"}

# === 转写参数 ===
ENGINE_MODEL = "16k_zh"
SPEAKER_NUM = 2
POLL_SECONDS = 5
MAX_TRIES = 120

# === 免费额度配置 ===
FREE_HOURS_PER_DAY = 10  # 每天免费10小时
MAX_FILE_SIZE_MB = 4.5   # 切分阈值
SEGMENT_DURATION = 180   # 每段3分钟

# === 工具路径 ===
def find_tool(tool_name):
    """查找工具的完整路径"""
    # 确保 PATH 包含常见路径
    os.environ['PATH'] = '/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:' + os.environ.get('PATH', '')
    
    common_paths = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin"
    ]
    
    tool_path = shutil.which(tool_name)
    if tool_path:
        return tool_path
    
    for path in common_paths:
        full_path = os.path.join(path, tool_name)
        if os.path.exists(full_path) and os.access(full_path, os.X_OK):
            return full_path
    
    return None

FFMPEG = find_tool("ffmpeg") or "ffmpeg"
FFPROBE = find_tool("ffprobe") or "ffprobe"

# === 颜色输出 ===
def print_info(msg):
    print(f"\033[0;32m[信息]\033[0m {msg}")

def print_error(msg):
    print(f"\033[0;31m[错误]\033[0m {msg}")

def print_step(msg):
    print(f"\033[0;34m[步骤]\033[0m {msg}")

def print_warning(msg):
    print(f"\033[1;33m[警告]\033[0m {msg}")

def print_success(msg):
    print(f"\033[0;32m[成功]\033[0m {msg}")

# === 时长工具 ===
def get_audio_duration(file_path):
    """获取音频时长（秒）"""
    try:
        result = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            duration = result.stdout.strip()
            if duration != 'N/A':
                return float(duration)
    except Exception:
        pass
    return 0

def format_duration(seconds):
    """格式化时长"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}小时{minutes}分{secs}秒"
    elif minutes > 0:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"

# === 进度管理 ===
def load_progress(progress_file):
    """加载进度"""
    if Path(progress_file).exists():
        with open(progress_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "completed": [],
        "failed": [],
        "day1_duration": 0,
        "day2_duration": 0,
        "total_duration": 0,
        "last_update": None
    }

def save_progress(progress_file, progress):
    """保存进度"""
    progress["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

# === 腾讯云API ===
def sign_tc3(service, host, action, version, payload, timestamp, secret_id, secret_key, region):
    """生成腾讯云 TC3-HMAC-SHA256 签名"""
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    ct = "application/json; charset=utf-8"
    payload_str = json.dumps(payload)
    canonical_request = (
        f"POST\n/\n\n"
        f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n\n"
        f"content-type;host;x-tc-action\n"
        f"{hashlib.sha256(payload_str.encode()).hexdigest()}"
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = (
        "TC3-HMAC-SHA256\n"
        f"{timestamp}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    def _hmac(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()
    secret_date = _hmac(("TC3"+secret_key).encode(), date)
    secret_service = hmac.new(secret_date, service.encode(), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders=content-type;host;x-tc-action, Signature={signature}"
    )
    return {
        "Authorization": auth,
        "Content-Type": ct,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }

def create_task(audio_path, secret_id, secret_key, region):
    """创建转写任务"""
    with open(audio_path, "rb") as f:
        data = f.read()
    payload = {
        "EngineModelType": ENGINE_MODEL,
        "ChannelNum": 1,
        "ResTextFormat": 0,
        "SourceType": 1,
        "Data": base64.b64encode(data).decode(),
        "DataLen": len(data),
        "SpeakerDiarization": 1,
        "SpeakerNumber": SPEAKER_NUM,
    }
    ts = int(time.time())
    headers = sign_tc3("asr", "asr.tencentcloudapi.com", "CreateRecTask", "2019-06-14", payload, ts, secret_id, secret_key, region)
    r = requests.post("https://asr.tencentcloudapi.com", headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    resp = r.json()
    if "Error" in resp.get("Response", {}):
        raise RuntimeError(resp["Response"]["Error"]["Message"])
    return resp["Response"]["Data"]["TaskId"]

def poll_result(task_id, secret_id, secret_key, region):
    """轮询任务结果"""
    for i in range(MAX_TRIES):
        time.sleep(POLL_SECONDS)
        payload = {"TaskId": task_id}
        ts = int(time.time())
        headers = sign_tc3("asr", "asr.tencentcloudapi.com", "DescribeTaskStatus", "2019-06-14", payload, ts, secret_id, secret_key, region)
        r = requests.post("https://asr.tencentcloudapi.com", headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json().get("Response", {}).get("Data", {})
        status = data.get("Status")
        if status in (0, 1):
            print(f"      [{i+1}] 处理中...")
            continue
        if status == 2:
            return data
        if status == 3:
            raise RuntimeError(data.get("ErrorMsg", "未知错误"))
    raise TimeoutError("转写超时")

# === 音频处理 ===
def split_audio(file_path, output_dir, segment_duration=SEGMENT_DURATION):
    """使用 ffmpeg 切分音频文件"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    stem = Path(file_path).stem
    ext = Path(file_path).suffix
    
    duration = get_audio_duration(file_path)
    if duration == 0:
        print_error(f"无法获取音频时长: {file_path}")
        return []
    
    num_segments = int(duration // segment_duration) + 1
    print_info(f"音频时长: {duration:.1f}秒，将切分为 {num_segments} 段")
    
    segments = []
    for i in range(num_segments):
        start_time = i * segment_duration
        output_file = Path(output_dir) / f"{stem}_part{i:03d}{ext}"
        
        cmd = [
            FFMPEG, '-y', '-i', str(file_path),
            '-ss', str(start_time),
            '-t', str(segment_duration),
            '-c', 'copy',
            str(output_file)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and output_file.exists():
            segments.append({
                'path': output_file,
                'start_time': start_time,
                'index': i
            })
            print_info(f"  切分片段 {i+1}/{num_segments}: {output_file.name}")
        else:
            print_warning(f"  切分片段 {i+1} 失败")
    
    return segments

def adjust_timestamps(result_text, offset_seconds):
    """调整时间戳偏移"""
    lines = result_text.strip().split('\n')
    adjusted_lines = []
    
    for line in lines:
        if not line.strip():
            continue
        try:
            bracket_end = line.index(']')
            timestamp_part = line[1:bracket_end]
            text_part = line[bracket_end+1:].strip()
            
            parts = timestamp_part.split(',')
            if len(parts) >= 3:
                def parse_time(t):
                    t = t.strip()
                    if ':' in t:
                        parts = t.split(':')
                        return float(parts[0]) * 60 + float(parts[1])
                    return float(t)
                
                def format_time(seconds):
                    mins = int(seconds // 60)
                    secs = seconds % 60
                    return f"{mins}:{secs:.3f}"
                
                start = parse_time(parts[0]) + offset_seconds
                end = parse_time(parts[1]) + offset_seconds
                speaker = parts[2].strip()
                
                adjusted_line = f"[{format_time(start)},{format_time(end)},{speaker}]  {text_part}"
                adjusted_lines.append(adjusted_line)
            else:
                adjusted_lines.append(line)
        except:
            adjusted_lines.append(line)
    
    return '\n'.join(adjusted_lines)

def process_single_file(file_path, temp_dir, secret_id, secret_key, region):
    """处理单个文件"""
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    stem = file_path.stem
    
    if file_size_mb <= MAX_FILE_SIZE_MB:
        print_info(f"文件大小: {file_size_mb:.2f} MB（直接上传）")
        task_id = create_task(file_path, secret_id, secret_key, region)
        print_info(f"TaskId: {task_id}")
        data = poll_result(task_id, secret_id, secret_key, region)
        return data.get("Result", ""), [data]
    else:
        print_info(f"文件大小: {file_size_mb:.2f} MB（需要切分）")
        
        temp_seg_dir = Path(temp_dir) / stem
        if temp_seg_dir.exists():
            shutil.rmtree(temp_seg_dir)
        
        segments = split_audio(file_path, temp_seg_dir)
        if not segments:
            raise RuntimeError("切分失败")
        
        all_results = []
        all_texts = []
        
        for seg in segments:
            seg_path = seg['path']
            seg_start = seg['start_time']
            seg_size_mb = seg_path.stat().st_size / (1024 * 1024)
            
            print_info(f"  转写片段 {seg['index']+1}/{len(segments)}: {seg_path.name} ({seg_size_mb:.2f} MB)")
            
            try:
                task_id = create_task(seg_path, secret_id, secret_key, region)
                print_info(f"    TaskId: {task_id}")
                data = poll_result(task_id, secret_id, secret_key, region)
                result_text = data.get("Result", "")
                
                adjusted_text = adjust_timestamps(result_text, seg_start)
                all_texts.append(adjusted_text)
                all_results.append(data)
                
                print_info(f"    ✅ 片段转写完成")
            except Exception as e:
                print_error(f"    ✗ 片段转写失败: {e}")
        
        shutil.rmtree(temp_seg_dir)
        
        merged_text = '\n'.join(all_texts)
        return merged_text, all_results

def save_outputs(output_dir, audio_path, result_text, raw_data_list):
    """保存转写结果"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    stem = Path(audio_path).stem
    raw_path = Path(output_dir) / f"{stem}.json"
    txt_path = Path(output_dir) / f"{stem}.txt"
    
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data_list, f, ensure_ascii=False, indent=2)
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"转写文件：{audio_path.name}\n")
        f.write(f"转写时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"转写工具：腾讯云ASR\n")
        f.write("=" * 60 + "\n\n")
        f.write(result_text)
    
    print_info(f"保存转写文本: {txt_path}")
    return txt_path

# === 主逻辑 ===
def scan_files(input_dir):
    """扫描所有音频文件并计算时长"""
    print_info("扫描音频文件...")
    files = []
    for p in sorted(Path(input_dir).iterdir()):
        if p.suffix.lower() in SUPPORTED and p.is_file():
            duration = get_audio_duration(p)
            files.append({
                'path': p,
                'name': p.name,
                'duration': duration,
                'size_mb': p.stat().st_size / (1024 * 1024)
            })
    return files

def plan_batches(files, progress):
    """规划分批处理"""
    completed = set(progress.get("completed", []))
    pending = [f for f in files if f['name'] not in completed]
    pending.sort(key=lambda x: x['duration'])
    
    day1_files = []
    day2_files = []
    day1_duration = 0
    day2_duration = 0
    
    for f in pending:
        duration_hours = f['duration'] / 3600
        if day1_duration + duration_hours <= FREE_HOURS_PER_DAY:
            day1_files.append(f)
            day1_duration += duration_hours
        else:
            day2_files.append(f)
            day2_duration += duration_hours
    
    return {
        'day1': day1_files,
        'day2': day2_files,
        'day1_duration': day1_duration,
        'day2_duration': day2_duration
    }

def show_status(input_dir, output_dir, progress_file):
    """显示当前状态"""
    print("=" * 70)
    print("腾讯云免费转写 - 状态查看")
    print("=" * 70)
    
    progress = load_progress(progress_file)
    files = scan_files(input_dir)
    batches = plan_batches(files, progress)
    
    total_files = len(files)
    total_duration = sum(f['duration'] for f in files)
    completed_count = len(progress.get("completed", []))
    failed_count = len(progress.get("failed", []))
    
    print()
    print(f"【总体情况】")
    print(f"  音频文件总数: {total_files} 个")
    print(f"  总时长: {format_duration(total_duration)} ({total_duration/3600:.2f} 小时)")
    print()
    print(f"【处理进度】")
    print(f"  已完成: {completed_count} 个")
    print(f"  失败: {failed_count} 个")
    print(f"  待处理: {total_files - completed_count} 个")
    print()
    print(f"【分批计划】")
    print(f"  第1天: {len(batches['day1'])} 个文件, {batches['day1_duration']:.2f} 小时")
    print(f"  第2天: {len(batches['day2'])} 个文件, {batches['day2_duration']:.2f} 小时")
    print()
    print(f"【免费额度】")
    print(f"  每日免费: {FREE_HOURS_PER_DAY} 小时")
    if batches['day1_duration'] <= FREE_HOURS_PER_DAY and batches['day2_duration'] <= FREE_HOURS_PER_DAY:
        print(f"  预计费用: 0 元 ✅ (在免费额度内)")
    else:
        exceed = max(0, batches['day1_duration'] - FREE_HOURS_PER_DAY) + max(0, batches['day2_duration'] - FREE_HOURS_PER_DAY)
        print(f"  超出部分: {exceed:.2f} 小时")
        print(f"  预计费用: {exceed * 60 * 0.032:.2f} 元")
    print()
    
    if progress.get("last_update"):
        print(f"【最后更新】{progress['last_update']}")
    
    print("=" * 70)

def run_day(day_num, input_dir, output_dir, temp_dir, progress_file, secret_id, secret_key, region, auto_confirm=False):
    """运行指定天的转写任务"""
    print("=" * 70)
    print(f"腾讯云免费转写 - 第 {day_num} 天")
    print("=" * 70)
    
    # 检查 ffmpeg
    try:
        subprocess.run([FFMPEG, '-version'], capture_output=True, check=True)
        print_info(f"使用 ffmpeg: {FFMPEG}")
        print_info(f"使用 ffprobe: {FFPROBE}")
    except Exception as e:
        print_error(f"未找到 ffmpeg，请先安装: brew install ffmpeg (macOS) 或 apt install ffmpeg (Linux)")
        return
    
    progress = load_progress(progress_file)
    files = scan_files(input_dir)
    batches = plan_batches(files, progress)
    
    if day_num == 1:
        batch_files = batches['day1']
        batch_duration = batches['day1_duration']
    else:
        batch_files = batches['day2']
        batch_duration = batches['day2_duration']
    
    if not batch_files:
        print_success("没有需要处理的文件！")
        return
    
    print()
    print_info(f"输入目录: {input_dir}")
    print_info(f"输出目录: {output_dir}")
    print_info(f"待处理: {len(batch_files)} 个文件")
    print_info(f"预计时长: {batch_duration:.2f} 小时")
    print_info(f"免费额度: {FREE_HOURS_PER_DAY} 小时")
    
    if batch_duration > FREE_HOURS_PER_DAY:
        print_warning(f"注意: 今日任务超出免费额度 {batch_duration - FREE_HOURS_PER_DAY:.2f} 小时")
    else:
        print_success(f"今日任务在免费额度内 ✅")
    
    print("-" * 70)
    
    if not auto_confirm:
        confirm = input("是否开始转写? (y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return
    else:
        print_info("自动确认模式，开始转写...")
    
    print()
    
    results = []
    processed_duration = 0
    
    for idx, f in enumerate(batch_files, 1):
        file_path = f['path']
        duration = f['duration']
        
        print_step(f"[{idx}/{len(batch_files)}] 处理: {file_path.name}")
        print_info(f"时长: {format_duration(duration)}")
        
        try:
            result_text, raw_data = process_single_file(file_path, temp_dir, secret_id, secret_key, region)
            save_outputs(output_dir, file_path, result_text, raw_data)
            
            progress["completed"].append(file_path.name)
            processed_duration += duration
            save_progress(progress_file, progress)
            
            results.append((file_path.name, "✅ 成功"))
            print_success("转写完成")
            
        except Exception as e:
            print_error(f"✗ 失败: {e}")
            progress["failed"].append(file_path.name)
            save_progress(progress_file, progress)
            results.append((file_path.name, f"❌ 失败: {e}"))
        
        print("-" * 70)
    
    print()
    print("=" * 70)
    print("转写结果汇总")
    print("=" * 70)
    
    success_count = sum(1 for _, s in results if s.startswith("✅"))
    fail_count = len(results) - success_count
    
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")
    print(f"处理时长: {format_duration(processed_duration)}")
    print(f"结果保存在: {output_dir}")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(
        description='腾讯云语音识别批量转写工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 设置环境变量
  export TENCENT_SECRET_ID='your_secret_id'
  export TENCENT_SECRET_KEY='your_secret_key'
  
  # 查看状态
  python3 tencent_asr_batch.py --input ./audio --output ./transcripts --status
  
  # 第1天转写
  python3 tencent_asr_batch.py --input ./audio --output ./transcripts --day 1
  
  # 第2天转写
  python3 tencent_asr_batch.py --input ./audio --output ./transcripts --day 2
        """
    )
    parser.add_argument('--input', '-i', help='音频文件输入目录')
    parser.add_argument('--output', '-o', help='转写结果输出目录')
    parser.add_argument('--day', type=int, choices=[1, 2], help='运行第几天的任务（利用免费额度分批）')
    parser.add_argument('--status', action='store_true', help='查看当前状态')
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument('--yes', '-y', action='store_true', help='跳过确认直接执行')
    
    args = parser.parse_args()
    
    # 检查环境变量（仅在需要时）
    global SECRET_ID, SECRET_KEY, REGION
    if args.input or args.output or args.day or args.status or args.reset:
        SECRET_ID, SECRET_KEY, REGION = get_config()
        if not SECRET_ID or not SECRET_KEY:
            print_error("❌ 错误: 请设置环境变量 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY")
            print("   方法1: export TENCENT_SECRET_ID='your_id'")
            print("   方法2: 创建 .env 文件（需要 python-dotenv）")
            print("   获取密钥: https://console.cloud.tencent.com/cam/capi")
            sys.exit(1)
    
    # 如果没有提供必需参数，显示帮助
    if not args.input and not args.output and not args.status and not args.reset:
        parser.print_help()
        return
    
    if not args.input or not args.output:
        if args.reset:
            parser.print_help()
            print_error("重置进度需要指定 --input 和 --output")
        else:
            parser.print_help()
            print_error("--input 和 --output 参数是必需的")
        sys.exit(1)
    
    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()
    temp_dir = output_dir / "temp_segments"
    progress_file = output_dir / "progress.json"
    
    if not input_dir.exists():
        print_error(f"输入目录不存在: {input_dir}")
        sys.exit(1)
    
    if args.reset:
        if progress_file.exists():
            progress_file.unlink()
        print_success("进度已重置")
        return
    
    if args.status or (not args.day):
        show_status(input_dir, output_dir, progress_file)
        return
    
    run_day(args.day, input_dir, output_dir, temp_dir, progress_file, SECRET_ID, SECRET_KEY, REGION, auto_confirm=args.yes)

if __name__ == "__main__":
    main()
