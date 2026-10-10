# DFPlayer

DFPlayer 是一个面向 Windows 的 MIDI 旋律播放器。它读取标准 MIDI 文件，将选定声部转换为单音旋律，并通过键盘与鼠标输入演奏。

## MIDI 资源

你可以从以下网站搜索或制作 MIDI 文件：

- [MidiShow](https://www.midishow.com/zh-tw)
- [Online Sequencer 曲目库](https://onlinesequencer.net/sequences)
- 其他提供 MIDI 文件的资源网站、社区或个人作品页

下载前请查看文件的作者、来源和许可条件。只有在个人使用、修改、分享或再分发均被允许的情况下，才应将文件放入项目的 `乐谱/` 目录或随软件包发布。DFPlayer 不为第三方 MIDI 文件提供授权，也不保证外部资源的版权状态。

## 使用范围

- Windows 10/11（64 位）
- 支持 `.mid`、`.midi`、`.kar`、`.rmi`
- 界面和命令行工具均为中文
- 播放输入仅适用于练习、自定义房间和单机环境

自动输入可能违反在线游戏的用户协议或反作弊规则，也可能导致账号处罚。使用前请确认目标软件允许自动输入，相关风险由使用者自行承担。

## 作者声明与官方渠道

- 作者：MingK1
- 官方仓库：[MingK1/Delta-Force-Harmonica-Player](https://github.com/MingK1/Delta-Force-Harmonica-Player)
- DFPlayer 免费开源，作者不会通过第三方平台出售软件。
- 未经作者授权，不得以作者名义收费分发、捆绑、修改发布或制作所谓“收费版”。
- 下载软件时请以官方仓库的 `Releases` 页面为准，不要相信其他网站、网盘或个人发布的收费链接。

## 功能

- 递归扫描 `乐谱` 目录并建立歌单
- 自动推荐主旋律声部，也可以手动选择声部
- 原始音轨、取最高音、天际线三种旋律模式
- 去除开头空拍、实时变速、实时移调
- 一键将旋律移入可演奏音域
- 播放、暂停、停止、上一首、下一首和进度定位
- 独立试听：只播放 MIDI 音频，不发送键盘或鼠标模拟输入
- 可配置全局热键
- 按曲目保存声部、速度和旋律模式

## 演奏范围和按键

- `Z X C V B N M`：基准八度的自然音
- `，`（键盘逗号）：高高音 do
- 鼠标左键：降低八度
- 鼠标右键：升高八度
- 鼠标中键：升半音
- 可演奏范围：低音 do 到高高音 #do；超出范围的音符会被跳过

默认全局热键：

| 热键 | 功能 |
| --- | --- |
| F6 | 播放/暂停 |
| F7 | 上一首 |
| F8 | 下一首 |
| F9 | 停止 |

## 使用教程

### 第一次使用

1. 下载一个 `.mid` 或 `.midi` 文件，并确认它的来源和使用许可。
2. 在 `DFPlayer` 目录中创建或打开 `乐谱` 文件夹，把 MIDI 文件放入其中。也可以使用电脑上的其他目录。
3. 启动 `DFPlayer.exe`。
4. 点击顶部的“选择乐谱目录”，选择刚才存放 MIDI 文件的文件夹。
5. 在左侧歌单中单击曲目。程序会自动读取声部并推荐一条主旋律轨。
6. 如果自动推荐不合适，在“主旋律声部”中选择其他轨道。
7. 双击曲目开始播放，或使用播放控制按钮。播放前请让目标游戏或应用获得焦点。

### 调整旋律

- **旋律提取**：单音轨可以使用“原始音轨”；带和弦的 MIDI 可以先试“取最高音”，复杂编曲可以试“天际线”。
- **一键进音域**：当大量音符超出演奏范围时，点击“一键进音域”自动寻找合适的移调值。
- **移调**：使用“移调”输入框按半音升降，范围为 `-24` 到 `+24`。
- **倍速**：使用“倍速”输入框调整播放速度，范围为 `0.1×` 到 `3.0×`。
- **去除开头空拍**：默认开启，会把第一个音符前的静音部分移除。
- **试听**：点击“试听”只使用 Windows MIDI 音频设备播放当前旋律，不会向目标游戏或应用发送按键；再次点击“停止试听”结束试听。

### 演奏时的注意事项

1. 建议使用窗口化或无边框窗口化模式，避免独占全屏无法接收模拟输入。
2. 点击播放后，再点击目标游戏或应用窗口，让它获得焦点。
3. 使用英文输入法，避免输入法拦截演奏键。
4. 演奏过程中不要移动角色、打开菜单或执行与演奏键冲突的操作。
5. 某些目标程序需要以管理员身份运行，DFPlayer 才能向其发送输入。
6. 发现输入异常时，使用 `F9` 或“停止”按钮立即释放所有按键。

### 曲目没有声音或旋律不完整

1. 点击“显示日志”查看 MIDI 读取和播放提示。
2. 回到“主旋律声部”重新选择一条非打击乐轨道。
3. 在“取最高音”和“天际线”之间切换并重新播放。
4. 尝试使用“一键进音域”或手动移调。
5. 如果文件本身缺少音符、只有打击乐或格式异常，请换一个 MIDI 文件。

## 从源码运行

在 `DFPlayer` 目录执行：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Python 需要 3.10 或更高版本。程序依赖 Tkinter，Windows 官方 Python 安装包通常已包含该组件。

## 清洗 MIDI

`midi_cleaner.py` 可以将多轨或带和弦的 MIDI 导出为单音旋律：

```powershell
python midi_cleaner.py "歌曲.mid" --list
python midi_cleaner.py "歌曲.mid"
python midi_cleaner.py "歌曲.mid" --part 1
python midi_cleaner.py "歌曲.mid" --skyline
python midi_cleaner.py "歌曲.mid" -o "干净.mid"
```

声部序号从 0 开始。默认使用取最高音模式，并移除开头空拍。

完整的命令行流程如下：

```powershell
# 1. 查看 MIDI 中有哪些声部
python midi_cleaner.py "乐谱\歌曲.mid" --list

# 2. 自动选择推荐声部并生成单音旋律
python midi_cleaner.py "乐谱\歌曲.mid"

# 3. 指定声部并使用天际线算法
python midi_cleaner.py "乐谱\歌曲.mid" --part 1 --skyline -o "乐谱\歌曲-单音.mid"
```

生成的 `.melody.mid` 或自定义输出文件可以直接放回歌单目录，然后点击“刷新”。

## 打包

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller build.spec
```

产物为 `dist/DFPlayer.exe`。打包配置会请求管理员权限，这是为了让 Windows 在目标程序以管理员权限运行时仍能接收模拟输入。

## 配置文件

设置保存在：

```text
%LOCALAPPDATA%\DFPlayer\settings.json
```

配置损坏或字段类型错误时，程序会回退到默认值并继续启动。

## 目录结构

```text
DFPlayer/
├── README.md
├── requirements.txt
├── build.spec
├── main.py
├── player.py
├── playback_engine.py
├── note_mapper.py
├── midi_loader.py
├── midi_cleaner.py
├── audio_preview.py
├── midi_audio.py
├── input_sender.py
├── hotkeys.py
├── config.py
└── 乐谱/
    └── *.mid
```

`乐谱/` 只应放入来源明确、允许再分发的 MIDI 文件。构建产物、缓存和本地配置不属于仓库内容。
