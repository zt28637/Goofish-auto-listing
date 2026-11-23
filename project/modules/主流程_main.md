# main  (flow_id=main, 组=—, 块数=8)
# 转录时间 2026-11-24 00:20 · 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1
# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep

001  打印日志  日志类型=info  日志内容=开始批量上架（三层编排）  [programing.log]
002  Try  [programing.try]
003  调用流程  模块名称=process2  arguments.清单路径=F:/Programs/RPA自动化/2-电商上架自动化/project/runtime/商品清单.xlsx  arguments.自动发布=表达式=True  →逐行上架  [process.run]
004  打印日志  日志类型=info  日志内容=表达式=f'批量上架完成：成功 {行汇总.成功数} 行 / 失败 {行汇总.失败数} 行'  [programing.log]
005  Catch  [programing.catch]
006  写入文件  要写入的文件=F:/Programs/RPA自动化/2-电商上架自动化/project/runtime/logs/shadowbot_error.txt  要写入的内容=表达式=f'批量上架异常：{exception}'  如果文件存在=overwrite  is_text=表达式=True  new_line=表达式=False  文件编码=UTF-8  [file.write]
007  打印日志  日志类型=error  日志内容=表达式=f'批量上架异常：{exception}'  [programing.log]
008  End Try  [programing.endtry]
