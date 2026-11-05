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

## Owner's correction (2026-11-06): the robot is a window version of a home floor robot
Owner's words: "the cleaning bots we have in the home, which cleans the floor. I think there were robots which does the same for Windows, right?"
Real products: Ecovacs WINBOT and HOBOT. All figures below come from retailer or manual listings, not lab tests:
- WINBOT W2: about 270 x 271 x 77 mm, 1.5-1.6 kg (sources conflict), 96 W brushless motor, 2600 mAh battery, leash with carabiner, about 55 m2 per charge. https://www.digitec.ch/en/s1/product/ecovacs-w2-window-cleaners-42863683 , https://aio.lv/en/product--ecovacs-w2--10850355.md
- WINBOT W2 Pro: up to 2800 Pa suction; vacuum sensor, safety tether, power protection; edge detection. https://www.inserv.lv/en/products/186584/window-cleaning-robot-with-2800-pa-suction-power-and-automatic-safety-system-white-ecovacs-winbot-w2-pro
- HOBOT-268/288: square vacuum body, UPS to hold on when power fails, listed max area 6 m high x 5 m wide. So these are home products, not high-rise products. https://www.manualslib.com/manual/1440045/Hobot-268.html?page=4
Science:
- Active vacuum adhesion is widely used; a robot falls or overturns when pressure difference drops below a threshold. https://www.mdpi.com/2218-6581/5/3/14 (check this is the review cited)
- A 2019 IEEE paper estimates adhesion from impeller motor current. https://repository.sutd.edu.sg/esploro/outputs/conferenceProceeding/Design-of-an-Adhesion-Aware-Façade-Cleaning/9912443509846
Honest framing: our robot scales a home robot design up for a high-rise, as a fictional product. No home model is sold for this job, as far as we found. Worked check for a W2-sized robot: 2800 Pa x about 0.04 m2 sealed area = about 112 N of hold force, against about 15 N of weight. Sealed area is an ASSUMPTION.
