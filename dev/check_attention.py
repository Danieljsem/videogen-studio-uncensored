"""Benchmark flash vs. memory-efficient SDPA attention on the GPU (Wan-sized tensors)."""
import os; os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL","1")
import torch, time, torch.nn.functional as F
torch.backends.cuda.enable_flash_sdp(True); torch.backends.cuda.enable_mem_efficient_sdp(True)
print("flash", torch.backends.cuda.flash_sdp_enabled(), "memeff", torch.backends.cuda.mem_efficient_sdp_enabled())
q=torch.randn(1,40,14040,128,device="cuda",dtype=torch.bfloat16)
from torch.nn.attention import sdpa_kernel, SDPBackend
for b in [SDPBackend.FLASH_ATTENTION, SDPBackend.EFFICIENT_ATTENTION]:
    try:
        torch.cuda.reset_peak_memory_stats()
        with sdpa_kernel([b]):
            F.scaled_dot_product_attention(q,q,q); torch.cuda.synchronize(); t=time.time()
            F.scaled_dot_product_attention(q,q,q); torch.cuda.synchronize()
        print(b, "OK", round(time.time()-t,2),"s peak", round(torch.cuda.max_memory_allocated()/1e9,1),"GB")
    except Exception as e: print(b,"FAIL",str(e)[:200])
