# DemoAgent 不运行 demo

DemoAgent 拥有全工具却唯独不执行运行类 shell 命令：生成 demo + 运行指南后由用户亲手运行，报错粘贴回 REPL 进入报错回传环（DemoAgent 诊断修改、用户再跑，受 Max_loop 约束）。运行权留在人手是为了把爆炸半径压到零（不自动起进程、不占端口、不装超时熔断那套）；诊断交回 agent 是为了不让用户人肉理解报错。
