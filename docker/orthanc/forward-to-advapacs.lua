-- Forward every stable study to AdvaPACS via DICOMweb STOW-RS.
-- "Stable" fires ~60s after the last received instance (Orthanc default).
--
-- AdvaPACS VALIDATION QUEUE NOTE:
-- If a study lacks an AccessionNumber, AdvaPACS accepts the STOW-RS and returns
-- HTTP 200 with a Retrieve URL (looks like success) but routes the study to a
-- Validation Queue rather than the main patient/study database. QIDO-RS will
-- return empty [] for these studies. The sidecar injects the OpenMRS accession
-- number during normal workflow; retag.py sets BPH-{PatientID} as a fallback
-- for direct uploads. The Validation Queue is not queryable via standard QIDO-RS.
function OnStableStudy(studyId, tags, metadata)
    local body = '{"Resources":["' .. studyId .. '"]}'
    local ok, err = pcall(function()
        RestApiPost('/dicom-web/servers/AdvaPACS/stow', body)
    end)
    if not ok then
        print('AdvaPACS STOW failed for study ' .. studyId .. ': ' .. tostring(err))
    end
end
