# Real high-rise cleaning robots: research notes (2026-11-06)

Owner's words: "look for actual robots which actually cleans mirrors, and use that as a reference. And please make it scientifically as accurate as possible".

## The real reference: an arm in a suspended cradle
Skyline Robotics Ozmo, as reported in the press and by the company:
- A robot arm rides in the building's existing window-cleaning cradle, with a control system for arm, tools and cradle.
- A waterproof six-axis KUKA KR AGILUS arm, reported as IP65.
- Force sensors set the contact pressure on each pane.
- Lidar for mapping, which has trouble with smooth transparent glass, so ultrasonic sensors were added, plus sensors for windowsills.
- Deployed at a 45-storey office tower in New York, with a human operator on the roof.
- "Three times faster" is the company's claim, not an independent measure.
Sources: https://www.therobotreport.com/skyline-robotics-ozmo-automates-skyscraper-window-cleaning/ , https://www.therobotreport.com/skyline-robotics-deploys-ozmo-window-cleaning-robot-new-york-city/

Other real design families (survey, not read in full): https://www.researchgate.net/publication/331452052_Survey_on_Glass_And_Facade-Cleaning_Robots_Climbing_Mechanisms_Cleaning_Methods_and_Applications

## Failure physics with some support
- Wind swings a gondola; a gondola-mounted cleaning robot paper uses H-infinity control to reduce the uncleaned area under obstacles. https://www.sciencedirect.com/science/article/abs/pii/S0957415823000016
- A patent gives a 30-35 km/h wind warning, citing crane safety limits. A vendor blog gives about 10 m/s as typical. Neither is independently validated. https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11351580
- A real incident: a gondola lost control in a wind gust at Shanghai World Financial Center, as cited in a review.
- Lidar on glass: a real sensing weakness, per the Ozmo reporting above.

## Not found
A measured wet-glass friction value, or a validated wind limit for a specific robot. Any such value in the sim is an assumption and must say so.
