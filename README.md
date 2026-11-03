# Zoe Tools

## Router Prompt Enhance

`ZoeNodes/tools → Router Prompt Enhance` 调用 Router 的 split-fix3 四分片 PE，输出可连接生图节点的增强文本。默认提示词及合并规则基于随需求提供的 `t2i_pe_core.py` Router 路径；后续 Router 更新时需同步此基线。

在 `comfyui-zoe-tools/.env` 中设置 `PROMPT_UPSAMPLER_API_KEY`；节点会自行读取，无须 `source`。也可设置 ComfyUI 进程环境变量，相同配置以环境变量为准。`.env` 支持 `KEY=value`、单引号、双引号、`export KEY=value` 和行尾注释，不执行 shell 命令或变量展开。base URL 默认是 `https://tokenhub.sensetime.com/v1`，可通过 `PROMPT_UPSAMPLER_BASE_URL` 更改，也可在节点中填写。可通过 `PROMPT_UPSAMPLER_MODEL` 设置默认模型。点击节点的“选择 / 刷新模型”从 `/models` 拉取并选择模型，也可手动填写。为避免通过刷新接口向任意地址发送密钥，刷新时节点地址须为 TokenHub 默认地址或 `PROMPT_UPSAMPLER_BASE_URL` 配置的地址。API Key 不会发送给浏览器或存入工作流。模型、max tokens、service tier、reasoning effort、超时、重试和画布设置均需与目标 Router 的实际配置核对。

- `user_prompt` 是用户生图需求；`system_prompt` 和四个分片模板可直接编辑，随工作流保存。每个模板必须恰好包含一个 `{{USER_VISUAL_REQUEST}}`。自动画布模式下 B 模板还必须保留 `CURRENT SHARD TASK: B · SPATIAL`。
- `mode=full` 并行运行四个分片，`enhanced_prompt` 输出 Router 合并后的 JSON 字符串。它可直接连接支持文本输入的生图节点。`debug_report` 提供运行汇总及回退、覆盖标记；`shards_json` 包含实际发送的 system/user 消息、原始响应、解析结果和分片统计，可接现有的 Show Text 节点查看。
- 选择单个分片时只运行该分片，`enhanced_prompt` 为空，不可用作完整生图提示词；查看 `shards_json`。完整输出需要运行 `full`。
- `canvas_mode=auto` 复现 Router 的自动画布及失败回退；`explicit` 使用提供的宽、高与比例。显式画布应与下游生图节点设置一致。
- 复制节点并修改提示词即可对比。改变 `run_id` 可以在其他输入不变时强制重新运行；不改变输入时 ComfyUI 可能复用缓存。每次完整执行会产生四个 LLM 请求，并可能发生重试和费用。固定生图参数和 seed 有助于比较，但不能保证 PE 模型的输出确定。

调试输出包括用户输入和模型响应，保存或分享工作流与调试记录时请自行留意内容。失败时节点抛出错误，不会默默把原始 prompt 当成增强结果。修改模板可能违反 Router 的固定字段契约；这样的结果必须修正后才能用于完整合并。创建新节点可恢复内置默认提示词。
