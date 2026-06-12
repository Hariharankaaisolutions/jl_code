#yolox_s.py

import os
from yolox.exp import Exp as MyExp

class Exp(MyExp):
    def __init__(self):
        super(Exp, self).__init__()
        # -------------------------------------------------------- #
        # 1. Basic Model Settings
        # -------------------------------------------------------- #
        # Standard YOLOX-S depth and width multipliers
        self.depth = 0.33    
        self.width = 0.50    
        self.exp_name = "yolox_s_harness_counting"

        # -------------------------------------------------------- #
        # 2. Dataset Settings
        # -------------------------------------------------------- #
        # CRITICAL: This must be 7 to match your .pth weight file
        self.num_classes = 5 
        
        # Standard image size (matches most YOLOX-S training)
        self.input_size = (640, 640)
        self.test_size = (640, 640)

        # -------------------------------------------------------- #
        # 3. Inference / Testing Settings
        # -------------------------------------------------------- #
        # These will be overridden by your video_config.txt in the main script,
        # but they serve as the model defaults.
        self.test_conf = 0.25  # Confidence threshold
        self.nmsthre = 0.45    # IOU threshold (Non-maximum suppression)