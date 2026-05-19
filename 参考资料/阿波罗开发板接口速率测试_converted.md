![](data:image/jpeg;base64...)

正点原子阿波罗开发板

1. 接口1：USB转UART（串口外接CH340同理，这里不做验证）

![](data:image/jpeg;base64...)

波特率：115200Bits/s

![](data:image/png;base64...)

![](data:image/png;base64...)

可以跑通，说明支持该速率

波特率：230400bits/s

![](data:image/png;base64...)

![](data:image/png;base64...)

可以跑通，说明支持该速率

波特率：921600bits/s

![](data:image/png;base64...)

![](data:image/png;base64...)

可以跑通，说明支持该速率

波特率：3000000bits/s

![](data:image/png;base64...)

![](data:image/png;base64...)

出现乱码，说明该速率无法跑通

尝试波特率：2000000bits/s

![](data:image/png;base64...)

![](data:image/png;base64...)

出现乱码，继续降低速率

波特率：1000000bits/s

![](data:image/png;base64...)

![](data:image/png;base64...)

出现乱码

结论：串口速率在921600bits/s以上，且不大于1000000bits/s，921600bits/s换算后（这里去除了起始位和停止位）为90KB/s或者0.087MB/s

1. 接口2：USB直连芯片，这里不是USB转UART连接芯片，而是直接连接，理论速率会更快（约1MB/s到1.2MB/s）

![](data:image/jpeg;base64...)

![](data:image/png;base64...)

通过测量，可以得知usb直连芯片的速率能够达到1.06MB/s