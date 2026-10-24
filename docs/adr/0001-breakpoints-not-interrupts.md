# 断点取代 interrupt

主工作流图内零 `interrupt()` 调用：所有"等用户"的时刻都是轮终断点——本轮跑完、状态由 checkpointer 落盘、控制权交还 REPL，用户下一条自由 prompt 融合进同 thread 续跑。选它而非 LangGraph 原生 interrupt，是因为交互形态是开放续写而非结构化选择（resume 值不进消息历史，自由 prompt 需要"融合执行"），且与正常 agent harness 的对话节律同构。唯一例外：shell 审批走 REPL 宿主层的同步审批回调，不进图。
