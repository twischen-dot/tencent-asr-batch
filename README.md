# 腾讯云语音识别批量转写工具

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)

利用腾讯云每日免费额度，智能分批处理大量音频文件的转写工具。支持自动分批、断点续传、大文件切分和说话人分离。

## ✨ 功能特点

- 🆓 **免费额度优化**：自动分批，充分利用每日10小时免费额度
- 🔄 **断点续传**：支持中断后继续，自动跳过已完成的文件
- 📦 **大文件切分**：自动切分超过4.5MB的文件
- 👥 **说话人分离**：自动识别不同说话人
- 📊 **进度保存**：实时保存进度，防止数据丢失
- 🎯 **智能分批**：自动规划分批处理，避免超出免费额度

## 📋 前置要求

1. **Python 3.7+**
2. **ffmpeg**（用于处理大文件）
   - macOS: `brew install ffmpeg`
   - Linux: `apt install ffmpeg` 或 `yum install ffmpeg`
3. **腾讯云账号**（需要 SecretId 和 SecretKey）

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置腾讯云密钥

**方法1：环境变量（推荐）**

```bash
export TENCENT_SECRET_ID='your_secret_id'
export TENCENT_SECRET_KEY='your_secret_key'
export TENCENT_REGION='ap-shanghai'  # 可选，默认 ap-shanghai
```

**方法2：使用 .env 文件**

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的密钥
```

然后安装 `python-dotenv`：
```bash
pip install python-dotenv
```

### 3. 查看转写状态

```bash
python3 tencent_asr_batch.py --input ./audio --output ./transcripts --status
```

### 4. 开始转写

**第1天（利用免费额度）：**
```bash
python3 tencent_asr_batch.py --input ./audio --output ./transcripts --day 1
```

**第2天（继续转写剩余文件）：**
```bash
python3 tencent_asr_batch.py --input ./audio --output ./transcripts --day 2
```

**自动确认模式（适合定时任务）：**
```bash
python3 tencent_asr_batch.py --input ./audio --output ./transcripts --day 1 --yes
```

## 📖 使用说明

### 命令行参数

| 参数 | 说明 | 必需 |
|------|------|------|
| `--input`, `-i` | 音频文件输入目录 | ✅ |
| `--output`, `-o` | 转写结果输出目录 | ✅ |
| `--day` | 运行第几天的任务（1或2） | ❌ |
| `--status` | 查看当前状态 | ❌ |
| `--reset` | 重置进度 | ❌ |
| `--yes`, `-y` | 跳过确认直接执行 | ❌ |

### 支持的音频格式

- `.m4a`
- `.mp3`
- `.wav`
- `.flac`
- `.aac`
- `.ogg`

### 输出文件

转写结果保存在输出目录：
- `*.txt` - 转写文本（带时间戳和说话人信息）
- `*.json` - 原始JSON数据
- `progress.json` - 进度记录文件

## 💰 费用说明

### 免费额度

- **新用户**：每日可享受 **10小时** 免费语音识别服务
- 免费额度按自然日计算，次日重置

### 付费标准

超出免费额度后，按以下标准计费（参考，实际以官网为准）：

- **0-299小时**：约 0.032元/分钟（约 1.92元/小时）
- **300-999小时**：约 0.028元/分钟（约 1.68元/小时）
- **1000小时以上**：约 0.024元/分钟（约 1.44元/小时）

**最新价格请查看**：https://cloud.tencent.com/product/asr/pricing

## 🔧 高级用法

### 定时任务（macOS）

创建定时任务，每天凌晨自动运行：

```bash
# 创建 launchd plist 文件
cat > ~/Library/LaunchAgents/com.user.tencent-asr.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.tencent-asr</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/tencent_asr_batch.py</string>
        <string>--input</string>
        <string>/path/to/audio</string>
        <string>--output</string>
        <string>/path/to/transcripts</string>
        <string>--day</string>
        <string>1</string>
        <string>--yes</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>TENCENT_SECRET_ID</key>
        <string>your_secret_id</string>
        <key>TENCENT_SECRET_KEY</key>
        <string>your_secret_key</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
EOF

# 加载任务
launchctl load ~/Library/LaunchAgents/com.user.tencent-asr.plist
```

## ⚠️ 注意事项

1. **保护密钥安全**：不要将密钥提交到代码仓库
2. **免费额度限制**：每日免费额度有限，大量文件建议分批处理
3. **网络连接**：需要稳定的网络连接访问腾讯云API
4. **文件大小**：单个文件超过5MB会自动切分处理
5. **说话人数量**：默认识别2个说话人，可在代码中修改 `SPEAKER_NUM`

## 🐛 常见问题

### Q: 提示 "Resource pack exhausted"
A: 免费额度已用完，等待明天重置或购买资源包。

### Q: 提示 "未找到 ffmpeg"
A: 请安装 ffmpeg：
- macOS: `brew install ffmpeg`
- Linux: `apt install ffmpeg`

### Q: 如何查看转写进度？
A: 使用 `--status` 参数：
```bash
python3 tencent_asr_batch.py --input ./audio --output ./transcripts --status
```

### Q: 如何重置进度重新开始？
A: 使用 `--reset` 参数：
```bash
python3 tencent_asr_batch.py --input ./audio --output ./transcripts --reset
```

## 📝 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📞 相关链接

- [腾讯云语音识别文档](https://cloud.tencent.com/document/product/1093)
- [腾讯云语音识别定价](https://cloud.tencent.com/product/asr/pricing)
- [获取 SecretId 和 SecretKey](https://console.cloud.tencent.com/cam/capi)

## ⭐ 如果这个项目对你有帮助，请给个 Star！

## 📦 安装

```bash
# 克隆仓库
git clone https://github.com/twischen-dot/tencent-asr-batch.git
cd tencent-asr-batch

# 安装依赖
pip install -r requirements.txt
```

## 🎯 使用场景

- 📞 **电话录音转写**：批量转写通话录音
- 🎙️ **会议记录**：自动生成会议文字记录
- 📚 **音频资料整理**：将音频资料转换为可搜索的文本
- ⚖️ **证据整理**：法庭证据录音的批量转写

## 🔗 相关链接

- **GitHub 仓库**: https://github.com/twischen-dot/tencent-asr-batch
- **问题反馈**: https://github.com/twischen-dot/tencent-asr-batch/issues
