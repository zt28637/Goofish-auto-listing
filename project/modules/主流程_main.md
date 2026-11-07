# main  (flow_id=main, 组=—, 块数=10)
# 转录时间 2026-11-07 10:48 · 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1
# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep

001  调用模块  模块名称=precheck  方法名称=main  方法参数列表=group_array=[kwargs=F:\\Programs\\RPA自动化\\2-电商上架自动化\\project\\runtime\\商品清单.xlsx]  返回值类型=str  [process.invoke_module]
002  设置变量  变量类型=str  变量值=表达式=str(预检结果)  [programing.variable]
003  从文本中提取内容  文本内容=变量=预检结果  提取方式=custom  正则表达式=fail=(\d+)  just_get_first=表达式=True  ignore_case=表达式=False  [text.extract_content_from_text]
004  IF 条件  对象1=变量=失败次数  关系=>  对象2=0  操作符参数={}  [workflow.if]
005  打印日志  日志类型=info  日志内容=预检不通过  [programing.log]
006  退出当前流程  [process.return]
007  End IF  [workflow.endif]
008  调用流程  模块名称=process3  →咸鱼_批量上架  [process.run]
009  获取当前日期时间  [datetime.now]
010  导出日志  文件夹路径=F:\Programs\RPA自动化\2-电商上架自动化\project\runtime\logs  文件名称=表达式=当前时间.strftime('%Y-%m-%d_%H-%M-%S')+'.txt'  [programing.exportlog]

## 审核疑点（2026-09-30 · 对照模块 .py 签名交叉核对，仅记录，未改画布）
- **011 路径拼写**：导出目录 `product_alllraw`（3个l），磁盘实际为 `runtime/product_allraw` → 会静默新建错误目录，下游按实际名找不到文件
- **019 多余且有害的 report 调用**：`output_path=input 竞品清洗Excel`（report.py 会覆盖清洗产物），023 再调用时读到的已是被日报覆盖的文件而非 13 列清洗表；015→019→023 三连里 019 疑似返工遗留，应删（023 单独保留即可，或改 output_path）
- **027 alert keyword 传错**：alert.py 的 `keyword` 是"搜索关键词（拼消息标题）"，画布传了 `glv['dingtalk_secret']`（钉钉加签密钥）→ 标题出现密钥字样=泄露；且 alert.py 本身不实现加签，机器人若为"加签"型则发送会 401（若是"自定义关键词"型，此参数应传关键词文本而非 secret）
- **012/016 重复赋值**：`竞品清洗Excel` 同一表达式赋值两次（冗余无害）

> 复核 2026-10-08（重转录后逐条对照新画布）：**四条疑点在原位置全部仍成立**（011/012/016/019/023/027 块号未变）。
