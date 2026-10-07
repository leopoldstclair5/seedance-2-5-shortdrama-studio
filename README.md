# Seedance 2.5 中文短剧制作工具包

这是一个可审阅、可恢复的短剧制作流程：先把一集剧本拆成稳定的场景 ID，再为角色维护定妆与连续性信息，最后让每个场景独立提交到 Seedance 2.5，保存 request_id，轮询并下载成片，使用 ffmpeg 合成。它是命令行工具包，不是假装已经存在的在线剪辑平台。

[查看 Seedance 2.5 模型页](https://argolink.io/en/models/seedance-2.5)，提交前以模型页的实时限制、价格和字段为准。仓库中的价格和参数只是在 2026-10-07 复核时的记录。

## 安装

需要 Python 3.9+、PyYAML 不是必需依赖、ffmpeg 和一个可用的 API key。本仓库只用 Python 标准库访问 HTTP。

~~~sh
git clone https://github.com/YOUR_ACCOUNT/seedance-2-5-shortdrama-studio
cd seedance-2-5-shortdrama-studio
python3 -m venv .venv
. .venv/bin/activate
export VIDEO_API_KEY='从密钥管理器注入'
ffmpeg -version
~~~

默认接口是 https://argolink.io/v1；兼容的本地测试服务可以通过 VIDEO_API_BASE_URL 替换。不要把 key 写进剧本、角色 JSON、提交记录或公开配置。

## 从剧本到分镜计划

最简单的计划不需要服务器调用。每个位置参数是一场戏，程序会生成场景 ID、5 秒默认时长、连续性提示以及待提交状态：

~~~sh
python -m drama.pipeline \
  --episode 1 \
  --title "旧钥匙" \
  --references https://cdn.example.test/xiaoyu.png https://cdn.example.test/station.png \
  --out episode-01-plan.json \
  "小雨在车站捡起一枚旧钥匙" \
  "她发现钥匙上的编号与失踪父亲的照片相同" \
  "雨停后她走向城南的旧影院"
~~~

生成的 JSON 可以先人工审阅，再交给 runner。更完整的角色表使用 JSON 文件：

~~~json
[
  {
    "id": "xiaoyu",
    "description": "二十多岁的短发女孩，眼神警觉",
    "wardrobe": "蓝色雨衣、灰色帆布包",
    "continuity_rules": ["左手戴银色手链", "不要改变发色"]
  }
]
~~~

~~~sh
python -m drama.pipeline --episode 1 --title "旧钥匙" \
  --characters characters.json \
  --references https://cdn.example.test/xiaoyu.png \
  --out episode-01-plan.json \
  "小雨在车站捡起一枚旧钥匙" \
  "她发现钥匙上的编号与失踪父亲的照片相同"
~~~

角色表是制作记录，不是模型的硬保证。把同一组参考图放入每个场景请求可以提供一致性线索，但仍需检查人物脸部、服装、道具、时间和屏幕方向。

程序只接受完整 HTTPS 参考 URL，不会把本地路径偷偷发给接口。需要本地素材时，先通过接口的媒体上传流程取得媒体 URL，再放进计划。

## 提交、恢复和合成

默认只写计划，不会产生网络请求。确认后加上 --run：

~~~sh
export VIDEO_API_KEY='从密钥管理器注入'
python -m drama.pipeline --episode 1 --title "旧钥匙" \
  --out episode-01-plan.json \
  --output-dir .drama/episode-01 \
  --output episode-01.mp4 \
  --run \
  "小雨在车站捡起一枚旧钥匙" \
  "她发现钥匙上的编号与失踪父亲的照片相同" \
  "雨停后她走向城南的旧影院"
~~~

runner 对每场戏只提交一次 POST /v1/videos/generations，收到 request_id 后立即写入 .drama/episode-01/manifest.json。它读取 GET /v1/videos/{request_id}，只接受 pending、done、failed、expired 四种状态；done 以后才读取 /content。manifest 每次提交、状态变化和下载都通过临时文件、fsync 和原子替换保存。进程中断后再次运行同一计划会复用已保存的 request_id，不会把超时当成重新提交的理由。

API 基础请求会带 Authorization、JSON 的 Content-Type 和明确的 User-Agent。此工具不在生成请求上做自动重试；如果 POST 超时且没有拿到 ID，先查服务端历史或账单，再决定是否继续。failed 或 expired 的响应会保留在 manifest，便于查原因。任务没有固定完成时间，请轮询状态而不是写死截止时间。

下载的文件在输出目录的 clips/scene-XX.mp4。下载使用临时文件和硬链接发布，不会覆盖已有文件。所有场景完成后，工具写入 ffconcat 清单并运行：

~~~text
ffmpeg -nostdin -y -f concat -safe 0 -i manifest.ffconcat \
  -c:v libx264 -pix_fmt yuv420p -c:a aac episode.mp4
~~~

素材顺序由场景顺序决定。保留各段原始视频，确认成片画面、对白、音轨和字幕之后再清理。

## Seedance 2.5 的边界和预算

2026-10-07 复核到的模型契约如下：

| 项目 | 当前值 |
| --- | --- |
| 时长 | 4–30 秒，整数秒 |
| 分辨率 | 480p、720p、1080p |
| 文字/参考比例 | 21:9、16:9、4:3、1:1、3:4、9:16 |
| 参考素材 | 最多 30 图、10 视频、10 音频，合计 50 |
| 参考视频/音频 | 每段 2–30 秒，每类合计最多 30 秒 |
| 提示词 | 最多 40,000 UTF-8 字节 |
| 输出 | 每次 1 条，24 fps H.264 MP4；默认有 AAC 立体声 |
| 计费 | 输出秒数；参考视频秒数另计 |

当前有效价为 480p 每秒 0.0874 USD、720p 每秒 0.196 USD、1080p 每秒 0.483 USD；官方目录价分别是 0.1028、0.2311、0.5686 USD。三场各 5 秒的 720p 粗算是 2.94 USD，有参考视频或重复提交时还会增加。失败、拒绝和过期任务不收费的前提以模型页和账户合同为准。

作为外部比较，[Evolink 的 Seedance 2.5 页面](https://evolink.ai/seedance-2-5)当前公布了约 0.138/0.296/0.739 USD 每秒的三档价格；[fal.ai 页面](https://fal.ai/models/bytedance/seedance-2.5/text-to-video)使用 token 计费并给出 720p 示例。比较页面不能替代本接口的字段和计费规则。

## 错误处理

400 是参数错误；401 是 key 缺失或无效；402 是账户余额或计费问题；404 是 request_id 不存在；409 表示成片尚未准备好；424 表示任务失败；429 和 503 表示暂时不可用。保留响应正文和 request_id，不要吞掉错误。429/503 是否重试要遵守服务端 Retry-After，并且只能重试同一个可确认的请求，不要复制一个新的场景。

## 测试

~~~sh
python -m unittest discover -s tests -v
python -m py_compile drama/pipeline.py
~~~

测试覆盖计划校验、角色与参考图映射、HTTPS 限制、鉴权和 User-Agent、未知状态和 ffmpeg 命令生成。测试使用本地假的 HTTP 响应和假的 ffmpeg 调用，不会访问生产接口，也不会产生计费请求。
