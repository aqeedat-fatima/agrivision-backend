import io
from typing import Dict, Any, Tuple, List

import torch
import torch.nn as nn
from torchvision import transforms
from torchvision.models import efficientnet_b3  # matches your notebook
from PIL import Image


# -----------------------------
# 1. Constants / label mapping
# -----------------------------


CLASS_NAMES: List[str] = [
    "Bacterial Blight",
    "Curl Virus",
    "Healthy Leaf",
    "Herbicide Growth Damage",
    "Leaf Hopper Jassids",
    "Leaf Redding",
    "Leaf Variegation",
]

NUM_CLASSES = len(CLASS_NAMES)

# Same transforms as your val_test_transform in the notebook
INFERENCE_TRANSFORM = transforms.Compose([
    transforms.Resize((300, 300)),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225]
    ),
])


# -----------------------------
# 2. Model construction
# -----------------------------

def build_model(num_classes: int = NUM_CLASSES) -> nn.Module:
    """
    Rebuild EfficientNet-B3 in the SAME way as in training,
    then replace the final classifier layer.
    """
    # In training you did:
    #   weights = EfficientNet_B3_Weights.IMAGENET1K_V1
    #   model = efficientnet_b3(weights=weights)
    #
    # For inference we can skip loading ImageNet weights, because
    # we'll immediately load your fine-tuned state_dict.
    model = efficientnet_b3(weights=None)

    in_features = model.classifier[1].in_features  # (Dropout, Linear)
    model.classifier[1] = nn.Linear(in_features, num_classes)

    return model


class CottonDiseaseModel:
    """
    Small helper class wrapping:
    - loading weights
    - preprocessing image
    - running prediction
    """

    def __init__(self, weights_path: str, device: str | None = None):
        self.device = torch.device(
            device if device is not None
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )

        self.model = build_model(NUM_CLASSES)
        state_dict = torch.load(weights_path, map_location=self.device)
        self.model.load_state_dict(state_dict)
        self.model.to(self.device)
        self.model.eval()

        self.transform = INFERENCE_TRANSFORM

    # -------------------------
    # 3. Preprocess + predict
    # -------------------------

    def _preprocess(self, image_bytes: bytes) -> torch.Tensor:
        """
        Convert raw image bytes -> transformed tensor on the right device.
        """
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = self.transform(image).unsqueeze(0)  # add batch dim
        return tensor.to(self.device)

    @torch.inference_mode()
    def predict(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Run the model on one image and return label + confidence + full probas.
        """
        x = self._preprocess(image_bytes)
        logits = self.model(x)
        probs = torch.softmax(logits, dim=1)[0]

        conf, idx = torch.max(probs, dim=0)
        idx = idx.item()
        conf = float(conf)

        return {
            "pred_index": idx,
            "pred_label": CLASS_NAMES[idx],
            "confidence": conf,
            "probabilities": probs.cpu().tolist(),
        }
