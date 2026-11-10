"""Save the first, middle and last frame of a video side by side. Usage: frames.py video.mp4 out.png"""
import sys, imageio.v3 as iio, numpy as np
f = iio.imread(sys.argv[1]); print(f.shape)
idx = [0, len(f)//2, len(f)-1]
iio.imwrite(sys.argv[2], np.hstack([f[i] for i in idx]))
