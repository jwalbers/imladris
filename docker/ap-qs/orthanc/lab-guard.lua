-- PHI guard: only lab-generated (synthetic) studies may leave this Orthanc.
--
-- Loaded first in LuaScripts; forward-to-advapacs.lua and forward-to-qure.lua
-- call IsLabStudy() before sending anything to AdvaPACS or the Qure.ai simulator.
--
-- A study counts as lab data only if EVERY series carries an InstitutionName
-- from LAB_INSTITUTIONS. Lab ingestion paths stamp these:
--   sidecar acquisition_loop.py   INSTITUTION env ("Bophelong MDR-TB Hospital")
--   imladris-bophelong retag.py   "Bophelong MDR-TB Hospital"
--   qure-sim SC results           "Partners in Health (Imladris Lab)"
-- Real studies (outside hospitals, blank InstitutionName) are refused.
-- Fails closed: any lookup error means "not lab data".
--
-- Real PHI belongs in docker/phi-review only — never in this Orthanc.

LAB_INSTITUTIONS = {
    ['Bophelong MDR-TB Hospital']         = true,
    ['Partners in Health (Imladris Lab)'] = true,
}

function IsLabStudy(studyId)
    local ok, result = pcall(function()
        local study = ParseJson(RestApiGet('/studies/' .. studyId))
        if #study['Series'] == 0 then
            return false
        end
        for _, seriesId in ipairs(study['Series']) do
            local series = ParseJson(RestApiGet('/series/' .. seriesId))
            local tags = ParseJson(RestApiGet('/instances/' .. series['Instances'][1] .. '/simplified-tags'))
            local inst = tags['InstitutionName'] or ''
            if not LAB_INSTITUTIONS[inst] then
                print('PHI GUARD: study ' .. studyId .. ' series ' .. seriesId ..
                      ' has InstitutionName "' .. inst .. '" — not lab data, NOT forwarding')
                return false
            end
        end
        return true
    end)
    if not ok then
        print('PHI GUARD: lookup failed for study ' .. studyId .. ' (' .. tostring(result) .. ') — NOT forwarding')
        return false
    end
    return result
end
