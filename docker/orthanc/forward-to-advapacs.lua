-- Forward every stable study to AdvaPACS via DICOMweb STOW-RS.
-- "Stable" fires ~60s after the last received instance (Orthanc default).
function OnStableStudy(studyId, tags, metadata)
    local body = '{"Resources":["' .. studyId .. '"]}'
    RestApiPost('/dicom-web/servers/AdvaPACS/stow', body)
end
