# DFPlayer

DFPlayer 是一个面向 Windows 的 MIDI 旋律播放器。它读取标准 MIDI 文件，将选定声部转换为单音旋律，并通过键盘与鼠标输入演奏。

## 使用范围

- Windows 10/11（64 位）
- 支持 `.mid`、`.midi`、`.kar`、`.rmi`
- 界面和命令行工具均为中文
- 播放输入仅适用于练习、自定义房间和单机环境

自动输入可能违反在线游戏的用户协议或反作弊规则，也可能导致账号处罚。使用前请确认目标软件允许自动输入，相关风险由使用者自行承担。

## 功能

- 递归扫描 `乐谱` 目录并建立歌单
- 自动推荐主旋律声部，也可以手动选择声部
- 原始音轨、取最高音、天际线三种旋律模式
- 去除开头空拍、实时变速、实时移调
- 一键将旋律移入可演奏音域
- 播放、暂停、停止、上一首、下一首和进度定位
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
├── input_sender.py
├── hotkeys.py
├── config.py
└── 乐谱/
    └── *.mid
```

`乐谱/` 只应放入来源明确、允许再分发的 MIDI 文件。构建产物、缓存和本地配置不属于仓库内容。
