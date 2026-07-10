-- Forward CXR instances to the Qure.ai simulator gateway (QUREAI AE, port 5252).
--
-- Fires on every stored instance. CR and DX are chest X-ray modalities;
-- "RG" (Radiography) is also forwarded for completeness.
--
-- Skips forwarding if the study already contains an SC (Secondary Capture) series
-- so that repeated acquisitions or restarts do not accumulate duplicate qXR outputs.
--
-- The qure-sim service receives the DICOM, selects a sample Qure.ai annotated
-- output PNG, and C-STOREs it back as a Secondary Capture in the same study.
-- The result appears in OHIF as a "qXR AI Analysis" series alongside the original.
function OnStoredInstance(instanceId, tags, metadata, origin)
    local modality = tags['Modality']
    if modality ~= 'CR' and modality ~= 'DX' and modality ~= 'RG' then
        return
    end

    -- Look up the parent study and check for an existing SC series.
    local ok, result = pcall(function()
        local instance = ParseJson(RestApiGet('/instances/' .. instanceId))
        local seriesId = instance['ParentSeries']
        local series   = ParseJson(RestApiGet('/series/' .. seriesId))
        local studyId  = series['ParentStudy']
        local study    = ParseJson(RestApiGet('/studies/' .. studyId))

        for _, seriesId in ipairs(study['Series']) do
            local series = ParseJson(RestApiGet('/series/' .. seriesId))
            if series['MainDicomTags']['Modality'] == 'SC' then
                print('qure_sim: study ' .. studyId .. ' already has SC series — skipping')
                return true   -- signal: already done
            end
        end
        return false  -- no SC found
    end)

    if not ok then
        print('qure_sim: study lookup failed for ' .. instanceId .. ': ' .. tostring(result))
        return
    end

    if result then
        return  -- SC already present
    end

    print('qure_sim: forwarding ' .. modality .. ' instance ' .. instanceId)
    SendToModality(instanceId, 'QUREAI')
end
