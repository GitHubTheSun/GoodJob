# GoodJob

[中文](#中文) · [English](#english)

## 中文

贴在屏幕边上的记事和提醒。拖到屏幕边缘会吸附，鼠标移开就收回。

### 能做什么

- 记下今天、明天、后天的事，左右滑动切换
- 用 15 分钟、1 小时、2 小时、4 小时，或滑动条选具体时间
- 优先级：高优、优、中等、不急
- 点任务可以修改，点叉可以删除
- 把昨天没做完的事移到今天
- 中英文界面
- 四种风格：墨金、纸白、森绿、暮色
- 语音输入：说完后拆成多条记事和时间。需要网络。这台电脑如果访问不到 Google 语音，可在设置里填写 Groq API Key

### 运行

发布页下载 `GoodJob.exe`，双击即可。任务保存在本机 `%LOCALAPPDATA%\GoodJob`。

从源码运行：

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

## English

A docked notes and reminder panel. Drag it to a screen edge and it snaps there. Move the pointer away and it slides back.

### What it does

- Notes for today, tomorrow, and the day after, with a slide between days
- Quick times: 15 minutes, 1 hour, 2 hours, 4 hours, or a slider for an exact time
- Priority: high, plus, medium, low
- Click a note to edit it. Click × to delete it
- Move unfinished notes from yesterday onto today
- Chinese and English
- Four styles: Ink, Paper, Forest, Dusk
- Voice input splits one utterance into notes and times. It needs a network. If Google speech is unreachable, paste a Groq API key in Settings

### Run

Download `GoodJob.exe` from Releases and open it. Notes stay on this computer under `%LOCALAPPDATA%\GoodJob`.

From source:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```
