# UHM-9387: Patient DOB seem to be adjusted for timezones, could lead to an off-by-one-day DOB error.

- **URL:** https://pihemr.atlassian.net/browse/UHM-9387
- **Project:** PIHEMR (UHM)
- **Issue type:** Bug
- **Status:** Needs Assessment
- **Priority:** Unprioritized
- **Assignee:** James Albers
- **Reporter:** James Albers
- **Created:** 2026-07-08T03:14:36.356-0400
- **Updated:** 2026-10-20T20:22:02.620-0400

## Description

The Bophelong Hospital patient population (in the Imladris Lab OpenMRS lesotho-emr instance) all have birthdays on January 1 of their birth years.  1/1/1958, 1/1/2004, etc.

In OpenMRS views the DOBs appear to be adjusted for the local timezone, so when I look at patient DOBs here in the PDT time zone, they are all showing as 12/31/ of the prior year, e.g. 12/31/1957, 13/31/2003.

This could lead to a rare, but possible DOB mistake in referencing a person, especially in countries with many common first and last names, or inability to find a patient based on DOB when the timezone has moved the DOB one day ahead or behind of actual.

## Comments

### Mark Goodrich — 2026-07-08T12:24:27.747-0400

Yeah, this is known, frustrating issue (timezones are pain).

In the OpenMRS database, the date only stored as a date (with no time or timezone information).  We generally set the local time of the server to the local time of the health center(s) it serves.

However, generally the OpenMRS O2 strips out the time zone as well.

I’m wondering if this is a by-product of the new docker setup--there would be a problem, I’d think, if mysql (or it’s underlying docker container) is set to a different time zone than what Tomcat/Java is running in… are you able to check that @@James Albers

### James Albers — 2026-07-09T13:13:05.822-0400

@@Mark Goodrich investigating now.
