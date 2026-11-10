"""Print GPU VRAM and system RAM as seen by PyTorch."""
import torch, psutil
p=torch.cuda.get_device_properties(0)
f,t=torch.cuda.mem_get_info()
print("GPU",p.name,"VRAM total %.1f GB, free %.1f GB"%(t/2**30,f/2**30))
print("RAM total %.1f GB"%(psutil.virtual_memory().total/2**30))
