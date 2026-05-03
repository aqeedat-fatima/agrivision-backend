import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
from pathlib import Path

# ----------------------------
# Paths (FIXED for your setup)
# ----------------------------
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "cotton_validator.pth"

THRESHOLD = 0.80

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class CottonValidator:
    def __init__(self):
        # Load checkpoint
        checkpoint = torch.load(MODEL_PATH, map_location=device)

        # Class mappings
        self.class_to_idx = checkpoint["class_to_idx"]
        self.idx_to_class = {v: k for k, v in self.class_to_idx.items()}

        # Model architecture
        self.model = models.efficientnet_b0(weights=None)
        num_features = self.model.classifier[1].in_features
        self.model.classifier[1] = nn.Linear(num_features, 2)

        # Load weights
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model = self.model.to(device)
        self.model.eval()

        # Image preprocessing
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406],
                                 [0.229, 0.224, 0.225])
        ])

    def predict(self, image: Image.Image):
        # Convert image
        image = image.convert("RGB")
        image_tensor = self.transform(image).unsqueeze(0).to(device)

        # Inference
        with torch.no_grad():
            outputs = self.model(image_tensor)
            probs = torch.softmax(outputs, dim=1)

        # Cotton confidence
        cotton_idx = self.class_to_idx["cotton"]
        cotton_confidence = probs[0][cotton_idx].item()

        # Predicted class
        pred_idx = torch.argmax(probs, dim=1).item()
        pred_class = self.idx_to_class[pred_idx]

        # Validation decision
        is_valid = cotton_confidence >= THRESHOLD

        return {
            "is_valid": is_valid,
            "predicted_class": pred_class,
            "cotton_confidence": round(cotton_confidence * 100, 2)
        }


# Load once (important for performance)
cotton_validator = CottonValidator()