from pydicom.data import get_testdata_file
import pydicom
path = get_testdata_file("CT_small.dcm")
ds = pydicom.dcmread(path)
print("PatientID:", ds.PatientID)
print("Modality:", ds.Modality)
print("StudyDate:", ds.StudyDate)
print("BodyPartExamined:", ds.get("BodyPartExamined", "UNKNOWN"))