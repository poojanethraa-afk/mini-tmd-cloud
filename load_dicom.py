import os
import glob
import pydicom

folder = os.path.join(os.path.dirname(pydicom.__file__), "data", "test_files")
files = glob.glob(folder + "/**/*", recursive=True)

count = 0

with open("load.sql", "w") as out:
    for f in files:
        if not os.path.isfile(f):
            continue
        try:
            ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
        except Exception:
            continue

        modality = ds.get("Modality")
        if not modality:
            continue

        patient_id = str(ds.get("PatientID", "UNKNOWN"))
        body_part = str(ds.get("BodyPartExamined", "UNKNOWN"))

        d = str(ds.get("StudyDate", ""))
        if len(d) == 8:
            study_date = "'" + d[0:4] + "-" + d[4:6] + "-" + d[6:8] + "'"
        else:
            study_date = "NULL"

        patient_id = patient_id.replace("'", "''")
        body_part = body_part.replace("'", "''")

        out.write(
            "INSERT INTO studies (patient_id, modality, study_date, body_part) VALUES ('"
            + patient_id + "', '" + str(modality) + "', " + study_date + ", '" + body_part + "');\n"
        )
        count = count + 1

print("load.sql written with", count, "INSERT lines")