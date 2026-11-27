
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cv2

from backend.ai.employee_registry import EmployeeRegistry


def test_insightface_employee_recognition():
    registry = EmployeeRegistry("data/employees")

    # Load registered employee face photos (capped at 5 per employee for speed).
    registry.load_employees(max_photos_per_employee=5)

    # Test using a test image or sample photo from registered employees.
    test_path = "test_employee.jpg"
    if not os.path.exists(test_path):
        test_path = "data/employees/dharshan/image1.jpg"

    image = cv2.imread(test_path)

    if image is None:
        raise FileNotFoundError(f"Test image not found at: {test_path}")

    print(f"Testing recognition with: {test_path}")
    result = registry.recognize_employee(image)

    print("Recognition result:")
    print(result)
    assert result["status"] == "MATCHED"
    assert result["employee_id"] == "dharshan"


if __name__ == "__main__":
    test_insightface_employee_recognition()
