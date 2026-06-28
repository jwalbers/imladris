-- Forward CXR instances to the Qure.ai simulator gateway (QUREAI AE, port 5252).
--
-- Fires on every stored instance. CR and DX are chest X-ray modalities;
-- "RG" (Radiography) is also forwarded for completeness.
--
-- The qure-sim service receives the DICOM, selects a sample Qure.ai annotated
-- output PNG, and C-STOREs it back as a Secondary Capture in the same study.
-- The result appears in OHIF as a "qXR AI Analysis" series alongside the original.
function OnStoredInstance(instanceId, tags, metadata, origin)
    local modality = tags['Modality']
    if modality == 'CR' or modality == 'DX' or modality == 'RG' then
        print('qure_sim: forwarding ' .. modality .. ' instance ' .. instanceId)
        SendToModality(instanceId, 'QUREAI')
    end
end
