
import cv2
from backend.ai.employee_registry import EmployeeRegistry

registry = EmployeeRegistry("employee_faces")

print("Loading employee faces...")
registry.load_employees()

image = cv2.imread("test_employee.jpg")

if image is None:
    print("ERROR: test_employee.jpg not found in project folder")
else:
    result = registry.recognize_employee(image)
    print("Recognition result:")
    print(result)
