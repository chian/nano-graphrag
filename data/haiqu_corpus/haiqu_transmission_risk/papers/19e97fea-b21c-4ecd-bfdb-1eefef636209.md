[Skip to main content](https://www.nature.com/articles/s41598-024-57425-z#content)

Thank you for visiting nature.com. You are using a browser version with limited support for CSS. To obtain
the best experience, we recommend you use a more up to date browser (or turn off compatibility mode in
Internet Explorer). In the meantime, to ensure continued support, we are displaying the site without styles
and JavaScript.

Numerical performance of CO2 accumulation and droplet dispersion from a cough inside a hospital lift under different ventilation strategies


[Download PDF](https://www.nature.com/articles/s41598-024-57425-z.pdf)

[Download PDF](https://www.nature.com/articles/s41598-024-57425-z.pdf)

## Abstract

The impact of mechanical ventilation on airborne diseases is not completely known. The recent pandemic of COVID-19 clearly showed that additional investigations are necessary. The use of computational tools is an advantage that needs to be included in the study of designing safe places. The current study focused on a hospital lift where two subjects were included: a healthy passenger and an infected one. The elevator was modelled with a fan placed on the middle of the ceiling and racks for supplying air at the bottom of the lateral wall. Three ventilation strategies were evaluated: a without ventilation case, an upwards-blowing exhausting fan case and a downwards-blowing fan case. Five seconds after the elevator journey began, the infected person coughed. For the risk assessment, the CO2 concentration, droplet removal performance and dispersion were examined and compared among the three cases. The results revealed some discrepancies in the selection of an optimal ventilation strategy. Depending on the evaluated parameter, downward-ventilation fan or no ventilation strategy could be the most appropriate approach.

### Similar content being viewed by others

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41598-022-26837-0/MediaObjects/41598_2022_26837_Fig1_HTML.png)

### [Quantitative evaluation of precautions against the COVID-19 indoor transmission through human coughing](https://www.nature.com/articles/s41598-022-26837-0?fromPaywallRec=false)

ArticleOpen access30 December 2022

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41598-022-08067-6/MediaObjects/41598_2022_8067_Fig1_HTML.png)

### [3D modelling and simulation of the dispersion of droplets and drops carrying the SARS-CoV-2 virus in a railway transport coach](https://www.nature.com/articles/s41598-022-08067-6?fromPaywallRec=false)

ArticleOpen access07 March 2022

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41598-025-08394-4/MediaObjects/41598_2025_8394_Fig1_HTML.png)

### [Assessing HVAC airflow modulation strategies to reduce short-term aerosol transmission in office environments](https://www.nature.com/articles/s41598-025-08394-4?fromPaywallRec=false)

ArticleOpen access04 July 2025

## Introduction

Several breathing pandemics have occurred in recent decades[1](https://www.nature.com/articles/s41598-024-57425-z#ref-CR1 "Roychoudhury, S. et al. Viral pandemics of twenty-first century. J. Microb. Biotech. Food Sci 10, 711–716.                    https://doi.org/10.15414/jmbfs.2021.10.4.711-716                                     (2021)."). Moreover, there is a great likelihood of overcoming new pandemics in a few years[2](https://www.nature.com/articles/s41598-024-57425-z#ref-CR2 "The COVID-19 Pandemic: A Wake-up Call for Better Cooperation at the Science–Policy–Society Interface, vol. 62 (UN Department of Economic and Social Affairs (DESA) Policy Briefs, 2020)."). The main routes for transmitting breathing diseases include direct transmission via exhaled droplets, fomite transmission through contact with contaminated surfaces, inhalation of active viral or bacterial particles and contact with nonvolatile residual nuclei[3](https://www.nature.com/articles/s41598-024-57425-z#ref-CR3 "Tellier, R., Li, Y., Cowling, B. J. & Tang, J. W. Recognition of aerosol transmission of infectious agents: A commentary. BMC Infect. Dis. 19, 101.                    https://doi.org/10.1186/s12879-019-3707-y                                     (2019)."), [4](https://www.nature.com/articles/s41598-024-57425-z#ref-CR4 "Asadi, S. et al. Aerosol emission and superemission during human speech increase with voice loudness. Sci. Rep. 9, 2348.                    https://doi.org/10.1038/s41598-019-38808-z                                     (2019)."), [5](https://www.nature.com/articles/s41598-024-57425-z#ref-CR5 "Leung, N. H. L. et al. Respiratory virus shedding in exhaled breath and efficacy of face masks. Nat. Med. 26, 676–680.                    https://doi.org/10.1038/s41591-020-0843-2                                     (2020)."), [6](https://www.nature.com/articles/s41598-024-57425-z#ref-CR6 "van Doremalen, N. et al. Aerosol and surface stability of SARS-CoV-2 as compared with SARS-CoV-1. N. Engl. J. Med. 382, 1564–1567.                    https://doi.org/10.1056/NEJMc2004973                                     (2020)."), [7](https://www.nature.com/articles/s41598-024-57425-z#ref-CR7 "Morawska, L. et al. How can airborne transmission of COVID-19 indoors be minimised?. Environ. Int. 142, 105832.                    https://doi.org/10.1016/j.envint.2020.105832                                     (2020)."). Droplets and residual transmission are the main issues of several studies due to the complexity of preventing their transmission. The path along which a droplet travels depends on several factors, such as its initial velocity, the size of the particle, and other environmental parameters, such as relative humidity (RH), environmental temperature (T∞), and above all, the surrounding air velocity[8](https://www.nature.com/articles/s41598-024-57425-z#ref-CR8 "Kumar, S. & King, M. D. Numerical investigation on indoor environment decontamination after sneezing. Environ. Res. 213, 113665.                    https://doi.org/10.1016/j.envres.2022.113665                                     (2022)."), [9](https://www.nature.com/articles/s41598-024-57425-z#ref-CR9 "Bahramian, A., Mohammadi, M. & Ahmadi, G. Effect of indoor temperature on the velocity fields and airborne transmission of sneeze droplets: An experimental study and transient CFD modeling. Sci. Total Environ. 858, 159444.                    https://doi.org/10.1016/j.scitotenv.2022.159444                                     (2023)."), [10](https://www.nature.com/articles/s41598-024-57425-z#ref-CR10 "Yang, X. et al. Transmission of pathogen-laden expiratory droplets in a coach bus. J. Hazard. Mater. 397, 122609.                    https://doi.org/10.1016/j.jhazmat.2020.122609                                     (2020)."), [11](https://www.nature.com/articles/s41598-024-57425-z#ref-CR11 "Rodríguez, D., Urbieta, I. R., Velasco, Á., Campano-Laborda, M. Á. & Jiménez, E. Assessment of indoor air quality and risk of covid-19 infection in Spanish secondary school and university classrooms. Build. Environ. 226, 109717.                    https://doi.org/10.1016/j.buildenv.2022.109717                                     (2022)."), [12](https://www.nature.com/articles/s41598-024-57425-z#ref-CR12 "Ahmadzadeh, M. & Shams, M. Passenger exposure to respiratory aerosols in a train cabin: Effects of window, injection source, output flow location. Sustain. Cities Soc. 75, 103280.                    https://doi.org/10.1016/j.scs.2021.103280                                     (2021)."), [13](https://www.nature.com/articles/s41598-024-57425-z#ref-CR13 "Jiang, G., Li, F. & Hu, T. Transport characteristics and transmission risk of virus-containing droplets from coughing in outdoor windy environment. Toxics 10, 294.                    https://doi.org/10.3390/toxics10060294                                     (2022)."), [14](https://www.nature.com/articles/s41598-024-57425-z#ref-CR14 "Zhang, Y. et al. Distribution of droplet aerosols generated by mouth coughing and nose breathing in an air-conditioned room. Sustain. Cities Soc. 51, 101721.                    https://doi.org/10.1016/j.scs.2019.101721                                     (2019)."). To further complicate the calculations, evaporation also plays an important role[15](https://www.nature.com/articles/s41598-024-57425-z#ref-CR15 "Ugarte-Anero, A., Fernandez-Gamiz, U., Portal-Porras, K., Zulueta, E. & Urbina-Garcia, O. Computational characterization of the behavior of a saliva droplet in a social environment. Sci. Rep. 12, 6405.                    https://doi.org/10.1038/s41598-022-10180-5                                     (2022)."). According to RH and T∞, the evaporation ratio can high or low, leading to residual salt particles floating in the local volume; this residual accumulation is known as aerosol, and according to several studies, this path can be assumed to be similar to a gas[16](https://www.nature.com/articles/s41598-024-57425-z#ref-CR16 "Zhao, Y., Feng, Y. & Ma, L. Numerical evaluation on indoor environment quality during high numbers of occupied passengers in the departure hall of an airport terminal. J. Build. Eng. 51, 104276.                    https://doi.org/10.1016/j.jobe.2022.104276                                     (2022)."), [17](https://www.nature.com/articles/s41598-024-57425-z#ref-CR17 "Peng, Z. & Jimenez, J. L. Exhaled CO2 as a COVID-19 infection risk proxy for different indoor environments and activities. Environ. Sci. Technol. Lett. 8, 392–397.                    https://doi.org/10.1021/acs.estlett.1c00183                                     (2021)."), [18](https://www.nature.com/articles/s41598-024-57425-z#ref-CR18 "Pastor-Fernández, A., Cerezo-Narváez, A., Montero-Gutiérrez, P., Ballesteros-Pérez, P. & Otero-Mateo, M. Use of low-cost devices for the control and monitoring of CO2 concentration in existing buildings after the COVID era. Appl. Sci. 12, 3927.                    https://doi.org/10.3390/app12083927                                     (2022)."), [19](https://www.nature.com/articles/s41598-024-57425-z#ref-CR19 "Vouriot, C. V. M., Burridge, H. C., Noakes, C. J. & Linden, P. F. Seasonal variation in airborne infection risk in schools due to changes in ventilation inferred from monitored carbon dioxide. Indoor Air 31, 1154–1163.                    https://doi.org/10.1111/ina.12818                                     (2021)."), [20](https://www.nature.com/articles/s41598-024-57425-z#ref-CR20 "Schade, W., Reimer, V., Seipenbusch, M. & Willer, U. Experimental investigation of aerosol and CO2 dispersion for evaluation of COVID-19 infection risk in a concert hall. IJERPH 18, 3037.                    https://doi.org/10.3390/ijerph18063037                                     (2021)."). Thus, several studies have experimentally tracked human-emitted CO2 gas as an easy and inexpensive way to monitor aerosol dispersions in relation to the droplet solid residuals[21](https://www.nature.com/articles/s41598-024-57425-z#ref-CR21 "Zivelonghi, A. & Lai, M. Mitigating aerosol infection risk in school buildings: The role of natural ventilation, volume, occupancy and CO2 monitoring. Build. Environ. 204, 108139.                    https://doi.org/10.1016/j.buildenv.2021.108139                                     (2021)."), [22](https://www.nature.com/articles/s41598-024-57425-z#ref-CR22 "Huessler, E.-M., Hüsing, A., Vancraeyenest, M., Jöckel, K.-H. & Schröder, B. Air quality in an air ventilated fitness center reopening for pilot study during COVID-19 pandemic lockdown. Build. Environ. 219, 109180.                    https://doi.org/10.1016/j.buildenv.2022.109180                                     (2022)."), [23](https://www.nature.com/articles/s41598-024-57425-z#ref-CR23 "Yamamoto, M., Kawamura, A., Tanabe, S. & Hori, S. Predicting the infection probability distribution of airborne and droplet transmissions. Indoor Built Environ.                    https://doi.org/10.1177/1420326X221084869                                     (2023)."), [24](https://www.nature.com/articles/s41598-024-57425-z#ref-CR24 "Lu, Y. et al. Affordable measures to monitor and alarm nosocomial SARS-CoV-2 infection due to poor ventilation. Indoor Air 31, 1833–1842.                    https://doi.org/10.1111/ina.12899                                     (2021)."), [25](https://www.nature.com/articles/s41598-024-57425-z#ref-CR25 "Fantozzi, F., Lamberti, G., Leccese, F. & Salvadori, G. Monitoring CO 2 concentration to control the infection probability due to airborne transmission in naturally ventilated university classrooms. Architect. Sci. Rev. 65, 306–318.                    https://doi.org/10.1080/00038628.2022.2080637                                     (2022)."), [26](https://www.nature.com/articles/s41598-024-57425-z#ref-CR26 "Blocken, B. et al. Ventilation and air cleaning to limit aerosol particle concentrations in a gym during the COVID-19 pandemic. Build. Environ. 193, 107659.                    https://doi.org/10.1016/j.buildenv.2021.107659                                     (2021).").

Among the different origins of exhaled droplets, the most common and studied are speaking, coughing and sneezing[27](https://www.nature.com/articles/s41598-024-57425-z#ref-CR27 "Bourouiba, L. Turbulent gas clouds and respiratory pathogen emissions: Potential implications for reducing transmission of COVID-19. JAMA                    https://doi.org/10.1001/jama.2020.4756                                     (2020)."), [28](https://www.nature.com/articles/s41598-024-57425-z#ref-CR28 "Busco, G., Yang, S. R., Seo, J. & Hassan, Y. A. Sneezing and asymptomatic virus transmission. Phys. Fluids 32, 073309.                    https://doi.org/10.1063/5.0019090                                     (2020)."), [29](https://www.nature.com/articles/s41598-024-57425-z#ref-CR29 "Gwaltney, J. M. et al. Nose blowing propels nasal fluid into the paranasal sinuses. Clin. Infect. Dis. 30, 387–391.                    https://doi.org/10.1086/313661                                     (2000)."), [30](https://www.nature.com/articles/s41598-024-57425-z#ref-CR30 "Han, Z. Y., Weng, W. G. & Huang, Q. Y. Characterizations of particle size distribution of the droplets exhaled by sneeze. J. R. Soc. Interface. 10, 20130560.                    https://doi.org/10.1098/rsif.2013.0560                                     (2013)."), [31](https://www.nature.com/articles/s41598-024-57425-z#ref-CR31 "Fairchild, C. I. & Stampfer, J. F. Particle concentration in exhaled breath. Am. Ind. Hyg. Assoc. Journal 48, 948–949.                    https://doi.org/10.1080/15298668791385868                                     (1987)."), [32](https://www.nature.com/articles/s41598-024-57425-z#ref-CR32 "Papineni, R. S. & Rosenthal, F. S. The size distribution of droplets in the exhaled breath of healthy human subjects. J. Aerosol Med. 10, 105–116.                    https://doi.org/10.1089/jam.1997.10.105                                     (1997)."), [33](https://www.nature.com/articles/s41598-024-57425-z#ref-CR33 "Mahajan, R. P., Singh, P., Murty, G. E. & Aitkenhead, A. R. Relationship between expired lung volume, peak flow rate and peak velocity time during a voluntary cough manoeuvre. Br. J. Anaesth. 72, 298–301.                    https://doi.org/10.1093/bja/72.3.298                                     (1994)."), [34](https://www.nature.com/articles/s41598-024-57425-z#ref-CR34 "Chao, C. Y. H. et al. Characterization of expiration air jets and droplet size distributions immediately at the mouth opening. J. Aerosol Sci. 40, 122–133.                    https://doi.org/10.1016/j.jaerosci.2008.10.003                                     (2009)."), [35](https://www.nature.com/articles/s41598-024-57425-z#ref-CR35 "Gupta, J. K., Lin, C.-H. & Chen, Q. Characterizing exhaled airflow from breathing and talking. Indoor Air 20, 31–39.                    https://doi.org/10.1111/j.1600-0668.2009.00623.x                                     (2010)."). A more violent exhalation correlated to more numerous and larger droplets; thus, the quantity of virus inside the droplet is presumed to increase by several orders of magnitude[36](https://www.nature.com/articles/s41598-024-57425-z#ref-CR36 "Anzai, H. et al. Coupled discrete phase model and Eulerian wall film model for numerical simulation of respiratory droplet generation during coughing. Sci. Rep. 12, 14849.                    https://doi.org/10.1038/s41598-022-18788-3                                     (2022)."), [37](https://www.nature.com/articles/s41598-024-57425-z#ref-CR37 "Stadnytskyi, V., Anfinrud, P. & Bax, A. Breathing, speaking, coughing or sneezing: What drives transmission of SARS-CoV-2?. J. Intern. Med. 290, 1010–1027.                    https://doi.org/10.1111/joim.13326                                     (2021)."). Understanding the physics of droplets of different sizes is vital for predicting droplet behaviour inside a certain volume. In those terms, Wells[38](https://www.nature.com/articles/s41598-024-57425-z#ref-CR38 "Wells, W. F. On air-borne infection*: Study II. Droplets and droplet nuclei. Am. J. Epidemiol. 20, 611–618.                    https://doi.org/10.1093/oxfordjournals.aje.a118097                                     (1934).") experimentally studied the evaporation of a single droplet in a freefall. Xie et al.[39](https://www.nature.com/articles/s41598-024-57425-z#ref-CR39 "Xie, X., Li, Y., Chwang, A. T. Y., Ho, P. L. & Seto, W. H. How far droplets can move in indoor environments? Revisiting the wells evaporation? Falling curve. Indoor Air 17, 211–225.                    https://doi.org/10.1111/j.1600-0668.2007.00469.x                                     (2007).") expanded on this research and considered the effect of RH.

The application of computational fluid dynamics (CFD) simulations can affordability and realistically predict different risky scenarios and increase the understanding of the physics of droplets. Since the appearance of COVID-19, a large number of scientists have investigated the generation and dispersion of droplets and nuclei by using CFD; for example, Anzai et al.[36](https://www.nature.com/articles/s41598-024-57425-z#ref-CR36 "Anzai, H. et al. Coupled discrete phase model and Eulerian wall film model for numerical simulation of respiratory droplet generation during coughing. Sci. Rep. 12, 14849.                    https://doi.org/10.1038/s41598-022-18788-3                                     (2022).") modelled the entire upper respiratory tract covered by a mucous film to recreate droplet formation during a cough, and Bahramian et al.[9](https://www.nature.com/articles/s41598-024-57425-z#ref-CR9 "Bahramian, A., Mohammadi, M. & Ahmadi, G. Effect of indoor temperature on the velocity fields and airborne transmission of sneeze droplets: An experimental study and transient CFD modeling. Sci. Total Environ. 858, 159444.                    https://doi.org/10.1016/j.scitotenv.2022.159444                                     (2023).") recently marked the effect of T∞ on the velocity of droplets generated by a sneeze. Furthermore, a variety of health-related dangerous places were staged in different indoor environments with specific ventilation strategies, occupations, environmental conditions and breathing activities[14](https://www.nature.com/articles/s41598-024-57425-z#ref-CR14 "Zhang, Y. et al. Distribution of droplet aerosols generated by mouth coughing and nose breathing in an air-conditioned room. Sustain. Cities Soc. 51, 101721.                    https://doi.org/10.1016/j.scs.2019.101721                                     (2019)."), [40](https://www.nature.com/articles/s41598-024-57425-z#ref-CR40 "Motamedi, H., Shirzadi, M., Tominaga, Y. & Mirzaei, P. A. CFD modeling of airborne pathogen transmission of COVID-19 in confined spaces under different ventilation strategies. Sustain. Cities Soc. 76, 103397.                    https://doi.org/10.1016/j.scs.2021.103397                                     (2022)."), [41](https://www.nature.com/articles/s41598-024-57425-z#ref-CR41 "Quiñones, J. J. et al. Prediction of respiratory droplets evolution for safer academic facilities planning amid COVID-19 and future pandemics: A numerical approach. J. Build. Eng. 54, 104593.                    https://doi.org/10.1016/j.jobe.2022.104593                                     (2022)."), [42](https://www.nature.com/articles/s41598-024-57425-z#ref-CR42 "Pendar, M.-R. & Páscoa, J. C. Numerical modeling of the distribution of virus carrying saliva droplets during sneeze and cough. Phys. Fluids 32, 083305.                    https://doi.org/10.1063/5.0018432                                     (2020)."), [43](https://www.nature.com/articles/s41598-024-57425-z#ref-CR43 "Chung, J. H., Kim, S., Sohn, D. K. & Ko, H. S. Ventilation efficiency according to tilt angle to reduce the transmission of infectious disease in classroom. Indoor Built Environ. 32, 763–776.                    https://doi.org/10.1177/1420326X221135829                                     (2023)."), [44](https://www.nature.com/articles/s41598-024-57425-z#ref-CR44 "Ovando-Chacon, G. E. et al. Computational study of thermal comfort and reduction of CO2 levels inside a classroom. IJERPH 19, 2956.                    https://doi.org/10.3390/ijerph19052956                                     (2022)."), [45](https://www.nature.com/articles/s41598-024-57425-z#ref-CR45 "Sarhan, A. R., Naser, P. & Naser, J. COVID-19 aerodynamic evaluation of social distancing in indoor environments, a numerical study. J. Environ. Health Sci. Eng. 19, 1969–1978.                    https://doi.org/10.1007/s40201-021-00748-0                                     (2021)."), [46](https://www.nature.com/articles/s41598-024-57425-z#ref-CR46 "D’Alicandro, A. C., Capozzoli, A. & Mauro, A. Thermofluid dynamics and droplets transport inside a large university classroom: Effects of occupancy rate and volumetric airflow. J. Aerosol Sci. 175, 106285.                    https://doi.org/10.1016/j.jaerosci.2023.106285                                     (2024)."), [47](https://www.nature.com/articles/s41598-024-57425-z#ref-CR47 "Arpino, F. et al. CFD analysis of the air supply rate influence on the aerosol dispersion in a university lecture room. Build. Environ. 235, 110257.                    https://doi.org/10.1016/j.buildenv.2023.110257                                     (2023)."). Other authors included public transport[10](https://www.nature.com/articles/s41598-024-57425-z#ref-CR10 "Yang, X. et al. Transmission of pathogen-laden expiratory droplets in a coach bus. J. Hazard. Mater. 397, 122609.                    https://doi.org/10.1016/j.jhazmat.2020.122609                                     (2020)."), [12](https://www.nature.com/articles/s41598-024-57425-z#ref-CR12 "Ahmadzadeh, M. & Shams, M. Passenger exposure to respiratory aerosols in a train cabin: Effects of window, injection source, output flow location. Sustain. Cities Soc. 75, 103280.                    https://doi.org/10.1016/j.scs.2021.103280                                     (2021)."), [48](https://www.nature.com/articles/s41598-024-57425-z#ref-CR48 "Mboreha, C. A., Jianhong, S., Yan, W. & Zhi, S. Airflow and contaminant transport in innovative personalized ventilation systems for aircraft cabins: A numerical study. Sci. Technol. Built Environ. 28, 557–574.                    https://doi.org/10.1080/23744731.2022.2050632                                     (2022)."), [49](https://www.nature.com/articles/s41598-024-57425-z#ref-CR49 "Yang, Y. et al. Numerical investigation on the droplet dispersion inside a bus and the infection risk prediction. Appl. Sci. 12, 5909.                    https://doi.org/10.3390/app12125909                                     (2022)."), [50](https://www.nature.com/articles/s41598-024-57425-z#ref-CR50 "Shinohara, N. et al. Air exchange rates and advection-diffusion of CO2 and aerosols in a route bus for evaluation of infection risk. Indoor Air                    https://doi.org/10.1111/ina.13019                                     (2022)."), hospital environments[8](https://www.nature.com/articles/s41598-024-57425-z#ref-CR8 "Kumar, S. & King, M. D. Numerical investigation on indoor environment decontamination after sneezing. Environ. Res. 213, 113665.                    https://doi.org/10.1016/j.envres.2022.113665                                     (2022)."), [51](https://www.nature.com/articles/s41598-024-57425-z#ref-CR51 "Le, T.-L., Nguyen, T. T. & Kieu, T. T. A CFD study on the design optimization of airborne infection isolation room. Math. Probl. Eng. 2022, 1–10.                    https://doi.org/10.1155/2022/5419671                                     (2022)."), [52](https://www.nature.com/articles/s41598-024-57425-z#ref-CR52 "Liu, Z. et al. A novel approach for predicting the concentration of exhaled aerosols exposure among healthcare workers in the operating room. Build. Environ. 245, 110867.                    https://doi.org/10.1016/j.buildenv.2023.110867                                     (2023).") and, more specifically, elevators[53](https://www.nature.com/articles/s41598-024-57425-z#ref-CR53 "Du, C. & Chen, Q. Virus transport and infection evaluation in a passenger elevator with a COVID-19 patient. Indoor Air                    https://doi.org/10.1111/ina.13125                                     (2022)."), [54](https://www.nature.com/articles/s41598-024-57425-z#ref-CR54 "Liu, S. et al. Evaluation of airborne particle exposure for riding elevators. Build. Environ. 207, 108543.                    https://doi.org/10.1016/j.buildenv.2021.108543                                     (2022)."), [55](https://www.nature.com/articles/s41598-024-57425-z#ref-CR55 "Dbouk, T. & Drikakis, D. On airborne virus transmission in elevators and confined spaces. Phys. Fluids 33, 011905.                    https://doi.org/10.1063/5.0038180                                     (2021)."), [56](https://www.nature.com/articles/s41598-024-57425-z#ref-CR56 "Tipnis, P. M., Chaware, P. & Vaidya, V. G. Guidelines for elevator design to mitigate the risk of spread of airborne diseases. Microb. Risk Anal. 26, 100289.                    https://doi.org/10.1016/j.mran.2023.100289                                     (2024).").

In the present study, a small hospital elevator was modelled via CFD to recreate the dispersion of cough droplets and the accumulation of CO2 caused by breathing during a journey of 15 s. The ambient conditions were 25 °C and 50% RH. Two standing people were introduced facing each other and 20 cm away from the longitudinal axis. Breathing was modelled for both occupants, and one was an asymptomatic infected person, who coughed at second 5 from the start. The lift was equipped with a ceiling fan. Three simulations were carried out (1) without ventilation (NF), (2) with upwards blowing ventilation (UF), and (3) with downwards blowing ventilation (DF).

The major novelty of this research is the quantitative approach of removing droplets and residual nuclei among the three ventilation setups inside a small clinical elevator. The numerical use of CO2 as an aerosol tracer has been limitedly used but was used for this study for computational cost savings while maintaining reliability and realistic results.

## Numerical method

### Case description

The current study consists of CFD simulations with a hospital lift as a scenario. The lift dimensions were the same as those previously used in[57](https://www.nature.com/articles/s41598-024-57425-z#ref-CR57 "Chillón, S. A., Ugarte-Anero, A., Aramendia, I., Fernandez-Gamiz, U. & Zulueta, E. Numerical modeling of the spread of cough saliva droplets in a calm confined space. Mathematics 9, 574.                    https://doi.org/10.3390/math9050574                                     (2021).") and[58](https://www.nature.com/articles/s41598-024-57425-z#ref-CR58 "Chillón, S. A., Fernandez-Gamiz, U., Zulueta, E., Ugarte-Anero, A. & Urbina-Garcia, O. Numerical modeling of a sneeze, a cough and a continuum speech inside a hospital lift. Heliyon 9, e13370.                    https://doi.org/10.1016/j.heliyon.2023.e13370                                     (2023)."); this type of elevator is 2.1 meters (m) long, 1.2 m wide and 2 m tall. These measurements are in accordance with the regulations of European Standards (EN) 81-20 and EN 81-50. The lift was modelled with a 30 cm diameter circular hole in the centre of the ceiling. This hole was modelled as a wall, an upwards blowing fan and a downwards blowing air inlet, according to the studied case. Shinohara et al.[50](https://www.nature.com/articles/s41598-024-57425-z#ref-CR50 "Shinohara, N. et al. Air exchange rates and advection-diffusion of CO2 and aerosols in a route bus for evaluation of infection risk. Indoor Air                    https://doi.org/10.1111/ina.13019                                     (2022).") noted that the stream produced by a fan could be simplified by a simple hole. The air supply velocity through the fan was 6.5 meters/second (m/s) for both cases where ventilation was used. On one sidewall, three air supply racks were modelled; each rack was 0.01 centrimetre (cm) thick with a length of 1.5 m located 15 cm from the floor, and the vertical distance between each rack was 15 cm. The ambient inside was modelled under clinical conditions: 25 °C of temperature and 50% RH according to the UNE 100713:2005 normative.

Inside the lift, two 1.7 m tall humans were modelled face to face, spaced 1.5 m from each other. To reproduce breathing and coughing, human mannequins were configured with nose and mouth openings. The nostril outlets were two holes of elliptical appearance, approximately 1.7 cm in length and 0.5 cm in width. The mouth was a 4 cm long and 0.5 cm opening hole, in agreement with measurements from Dbouk and Drikakis[59](https://www.nature.com/articles/s41598-024-57425-z#ref-CR59 "Dbouk, T. & Drikakis, D. On coughing and airborne droplet transmission to humans. Phys. Fluids 32, 053310.                    https://doi.org/10.1063/5.0011960                                     (2020)."). More details are provided in Figs. [1](https://www.nature.com/articles/s41598-024-57425-z#Fig1), [2](https://www.nature.com/articles/s41598-024-57425-z#Fig2) and Table [1](https://www.nature.com/articles/s41598-024-57425-z#Tab1).

**Figure 1**

![Figure 1](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig1_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/1)

Dimensions of the computational domain: ( **a**) Front view; ( **b**) plan.

**Figure 2**

![Figure 2](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig2_HTML.jpg)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/2)

Details of the mouth and nose inlets.

**Table 1 Computational domain measurements.**

[Full size table](https://www.nature.com/articles/s41598-024-57425-z/tables/1)

Figure [3](https://www.nature.com/articles/s41598-024-57425-z#Fig3) a shows the velocity profiles of breathing and coughing with respect to the nose and mouth. The emitter breathing velocity profile was modelled as sinusoidal for exhalation and inhalation, with maximum peaks of 4.4 m/s for mouth breath and 2.2 m/s for nose breath, in accordance with Du and Chen[53](https://www.nature.com/articles/s41598-024-57425-z#ref-CR53 "Du, C. & Chen, Q. Virus transport and infection evaluation in a passenger elevator with a COVID-19 patient. Indoor Air                    https://doi.org/10.1111/ina.13125                                     (2022).") and Mhetre et al.[60](https://www.nature.com/articles/s41598-024-57425-z#ref-CR60 "Mhetre, M. R. & Abhyankar, H. K. Human exhaled air energy harvesting with specific reference to PVDF film. Eng. Sci. Technol. Int. J. 20, 332–339.                    https://doi.org/10.1016/j.jestch.2016.06.012                                     (2017)."). The breath was noncontinuous because the cough started at second 5 and ended at second 5.5. Similarly, the receptor breath was a cosine with the same velocity peaks. In this case, the breath was completely continuous at all times. The total cycle time of both breathings was 6 s. The pulmonary ventilation rate was 40.7 L/minute (33.6 L/minute across the mouth and 7.1 L/minute across the nose); this represents a ventilation rate that is near hyperventilation. The exhaled gases from the mouth were 78% N2, 17% O2 and 5% CO2, as noted in Hibbard et al.[61](https://www.nature.com/articles/s41598-024-57425-z#ref-CR61 "Hibbard, T. & Killard, A. J. Breath ammonia analysis: Clinical application and measurement. Crit. Rev. Anal. Chem. 41, 21–35.                    https://doi.org/10.1080/10408347.2011.521729                                     (2011)."). Only the cough emitter exhaled CO2, and this was modelled as the Eulerian phase, as done in different studies like in Pham et al.[62](https://www.nature.com/articles/s41598-024-57425-z#ref-CR62 "Pham, D. A., Lim, Y.-I., Jee, H., Ahn, E. & Jung, Y. Porous media Eulerian computational fluid dynamics (CFD) model of amine absorber with structured-packing for CO2 removal. Chem. Eng. Sci. 132, 259–270.                    https://doi.org/10.1016/j.ces.2015.04.009                                     (2015).") or Sadeghizadeh et al.[63](https://www.nature.com/articles/s41598-024-57425-z#ref-CR63 "Sadeghizadeh, A., Rahimi, R. & Farhad Dad, F. Computational fluid dynamics modeling of carbon dioxide capture from air using biocatalyst in an airlift reactor. Bioresour. Technol. 253, 154–164.                    https://doi.org/10.1016/j.biortech.2018.01.025                                     (2018)."). The exhaled CO2 was only monitored from the cough emitter to observe the CO2 increase caused by only the infected person. The cough total volume was 0.64 L.

**Figure 3**

![Figure 3](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig3_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/3)

Inlet velocity parameters: ( **a**) Breathing; ( **b**) Coughing.

The cough velocity profile can be divided into four phases, as shown in Fig. [3](https://www.nature.com/articles/s41598-024-57425-z#Fig3) b. In phase one, the air velocity immediately increased up to 17.7 m/s, and phase 2 showed a quick decrease lasting 0.23 s with an ending velocity of 3.9 m/s. Phase 3 showed a short decrease lasting 0.05 s with an ending velocity of 1.995 m/s. Phase 4 showed a slight decrease lasting 0.19 s with an ending velocity of 1.575 m/s. The total cough time was 0.5 s. This velocity profile was based on the study of Mahajan et al.[33](https://www.nature.com/articles/s41598-024-57425-z#ref-CR33 "Mahajan, R. P., Singh, P., Murty, G. E. & Aitkenhead, A. R. Relationship between expired lung volume, peak flow rate and peak velocity time during a voluntary cough manoeuvre. Br. J. Anaesth. 72, 298–301.                    https://doi.org/10.1093/bja/72.3.298                                     (1994).") and validated in[57](https://www.nature.com/articles/s41598-024-57425-z#ref-CR57 "Chillón, S. A., Ugarte-Anero, A., Aramendia, I., Fernandez-Gamiz, U. & Zulueta, E. Numerical modeling of the spread of cough saliva droplets in a calm confined space. Mathematics 9, 574.                    https://doi.org/10.3390/math9050574                                     (2021).") and[58](https://www.nature.com/articles/s41598-024-57425-z#ref-CR58 "Chillón, S. A., Fernandez-Gamiz, U., Zulueta, E., Ugarte-Anero, A. & Urbina-Garcia, O. Numerical modeling of a sneeze, a cough and a continuum speech inside a hospital lift. Heliyon 9, e13370.                    https://doi.org/10.1016/j.heliyon.2023.e13370                                     (2023).").

### Meshing

Due to the complex human body shapes, the computational volume was discretized using a polyhedral mesh of 667,917 cells. This mesh type is effectively coupled to different boundaries in a well-structured disposition. The mesh was divided into five volume controls (VC) with 5 different coarse levels. In Fig. [4](https://www.nature.com/articles/s41598-024-57425-z#Fig4), a transverse mesh plane is observed, along with the volume controls. The finest volume (VC1, 12,553 cells) was placed from the middle of the emitter’s head to 30 cm downstream in a 0.4 × 0.2 cm plane. VC2 (131,805 cells) was located in two areas (around VC1 and opposite from VC1), and the area opposite VC1 had the same volume and shape of VC1 but was located at the head of the receptor mannequin. VC3 (179,006 cells) was positioned between two humans. VC4 (311,497 cells) was located 15 cm from the ceiling and between 0.35 and 1.25 m from the floor. Finally, VC5 (33,056 cells), the coarsest grid, was placed at the bottom. A surface remesher was modelled for the two human bodies to obtain more accurate results for the mannequin shapes and to maintain an optimum geometry level.

**Figure 4**

![Figure 4](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig4_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/4)

Mesh grid.

To ensure the mesh-related independence of the numerical results, a mesh dependency study was performed using Richardson’s extrapolation, as explained in Roache[64](https://www.nature.com/articles/s41598-024-57425-z#ref-CR64 "Roache, P. J. Perspective: A method for uniform reporting of grid refinement studies. J. Fluids Eng. 116, 405–413.                    https://doi.org/10.1115/1.2910291                                     (1994)."). For this purpose, three meshes (fine, medium and coarse) with different refinement levels were configured. The cell size ratio was r ≈ 2. In the study, the axial velocity was measured 10 cm downstream from the mouth of the emitter. Tables [2](https://www.nature.com/articles/s41598-024-57425-z#Tab2), [3](https://www.nature.com/articles/s41598-024-57425-z#Tab3), [4](https://www.nature.com/articles/s41598-024-57425-z#Tab4) provide the different results obtained for the case of 17.7 m/s (the maximum cough velocity) in steady convergence.

**Table 2 Axial velocity results for each mesh.**

[Full size table](https://www.nature.com/articles/s41598-024-57425-z/tables/2)

**Table 3 Results for extrapolation and convergence order.**

[Full size table](https://www.nature.com/articles/s41598-024-57425-z/tables/3)

**Table 4 Relative errors and CGI values of the proposed meshes.**

[Full size table](https://www.nature.com/articles/s41598-024-57425-z/tables/4)

Equation ( [1](https://www.nature.com/articles/s41598-024-57425-z#Equ1)) shows the calculation for the extrapolated velocity; \\({\\text{h}}=0\\) represents the extrapolated most accurate result. Equation ( [2](https://www.nature.com/articles/s41598-024-57425-z#Equ2)) was used to calculate the order of convergence for a three-mesh grid convergence index study. The obtained results can be found in Table [3](https://www.nature.com/articles/s41598-024-57425-z#Tab3).

$${\\left({V}\_{ax}\\right)}\_{h=0}={\\left({V}\_{ax}\\right)}\_{1}+\\frac{{\\left({V}\_{ax}\\right)}\_{1}-{\\left({V}\_{ax}\\right)}\_{2}}{{r}^{p}-1}$$

(1)


$$p=\\frac{{\\text{ln}}\\left(\\frac{{\\left({V}\_{ax}\\right)}\_{3}-{\\left({V}\_{ax}\\right)}\_{2}}{{\\left({V}\_{ax}\\right)}\_{2}-{\\left({V}\_{ax}\\right)}\_{1}}\\right)}{{\\text{ln}}2}$$

(2)


where \\({V}\_{ax}\\) is the axial velocity (m/s), \\(r\\) is the cells incrementing ratio and \\(p\\) is the order of convergence.

Equations ( [3](https://www.nature.com/articles/s41598-024-57425-z#Equ3)) and ( [4](https://www.nature.com/articles/s41598-024-57425-z#Equ4)) can be used to calculate the mesh relative error. Using the recommended value of FS = 1.25 for a three-mesh comparison, both fine and coarse GCIs are solved with Eqs. ( [5](https://www.nature.com/articles/s41598-024-57425-z#Equ5)) and ( [6](https://www.nature.com/articles/s41598-024-57425-z#Equ6)).

$${\\epsilon }\_{12}=\\frac{{\\left({V}\_{ax}\\right)}\_{1}-{\\left({V}\_{ax}\\right)}\_{2}}{{\\left({V}\_{ax}\\right)}\_{1}}$$

(3)


$${\\epsilon }\_{23}=\\frac{{\\left({V}\_{ax}\\right)}\_{2}-{\\left({V}\_{ax}\\right)}\_{3}}{{\\left({V}\_{ax}\\right)}\_{2}}$$

(4)


$${GCI}\_{12}=\\frac{FS\\left\|{\\epsilon }\_{12}\\right\|}{{r}^{p}-1}\\cdot 100$$

(5)


$${GCI}\_{23}=\\frac{FS\\left\|{\\epsilon }\_{23}\\right\|{r}^{p}}{{r}^{p}-1}\\cdot 100$$

(6)


where \\(\\in \\) is the relative error between two given results, \\(FS\\) is the security factor and \\(GCI\\) term is the grid convergence index result.

To check that our solution is within the asymptotic range, Eq. ( [7](https://www.nature.com/articles/s41598-024-57425-z#Equ7)) is recommended. All the solutions can be found in Table [4](https://www.nature.com/articles/s41598-024-57425-z#Tab4).

$$\\frac{{GCI}\_{23}}{{r}^{p}\\cdot {GCI}\_{12}}\\approx 1$$

(7)


Equation ( [7](https://www.nature.com/articles/s41598-024-57425-z#Equ7)) shows that the fine mesh is reliable, with an estimated error of 1.346%.

### Numerical methods

First, a steady simulation was created, introducing only airflow created with the ventilation into the elevator until the data converged. This continuum phase was modelled as Eulerian. The ambient conditions inside the lift were configured with the unique flow velocities of the configured fan, air supply racks and mouth inlets. For the case where the fan was used to exhaust the air inside, the device was set up as a pressure outlet with a value of − 35 pascals (Pa), creating a maximum velocity outlet of 6.5 m/s in the zone attached to the fan. In contrast, for the case of a downwards-blowing fan, the fan was configured as a velocity inlet with the same velocity of 6.5 m/s. For both cases, the racks were set up as stagnation inlets. The climatic conditions represent a clinical atmosphere with a constant temperature of 25 °C and a relative humidity of 50%. To maintain these conditions, the air introduced through the fan or racks had the same composition as the initial conditions (99.002% air; 0.998% H2O). Figure [6](https://www.nature.com/articles/s41598-024-57425-z#Fig6) shows the convergence results for three different cases: without a fan, with an upwards blowing fan and with a downwards blowing fan. The Reynolds-averaged Navier–Stokes (RANS) mathematical model was used for the entire computational domain, with the _k-ε_ turbulence model, described by Alfonsi in[65](https://www.nature.com/articles/s41598-024-57425-z#ref-CR65 "Alfonsi, G. Reynolds-averaged Navier–Stokes equations for turbulence modeling. Appl. Mech. Rev. 62, 040802.                    https://doi.org/10.1115/1.3124648                                     (2009).") (Fig. [5](https://www.nature.com/articles/s41598-024-57425-z#Fig5)).

**Figure 5**

![Figure 5](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig5_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/5)

Velocity streamlines for the following cases: ( **a**) no fan, ( **b**) upwards-blowing fan and ( **c**) downwards blowing fan.

Second, once the airflow inside the elevator was in continuous motion, the simulation became implicit unsteady 2nd order. Therefore, the respiration and aerosols generated were modelled as the Lagrangian phase. The simulation is solved as a two-phase flow situation, introducing the two-way coupling module. Droplets, represented by particle clusters (parcels), are injected into the domain via surface injectors located at the emitter mouth. The samples were configured as pure water without any residue inside; thus, they directly disappeared from the domain when they were absolutely evaporated or when they touched any surface. The total injected mass flow was 6.7 mg according to the experiments carried out by Zhu et al.[66](https://www.nature.com/articles/s41598-024-57425-z#ref-CR66 "Zhu, S., Kato, S. & Yang, J.-H. Study on transport characteristics of saliva droplets produced by coughing in a calm indoor environment. Build. Environ. 41, 1691–1702.                    https://doi.org/10.1016/j.buildenv.2005.06.024                                     (2006)."). The injection occurred in 0.26 s. The diameter was selected based on the Rosin–Rammler distribution, as shown in Eq. ( [8](https://www.nature.com/articles/s41598-024-57425-z#Equ8)). The selected diameter range was from 10 to 300 µm (µm), with a mean diameter of 80 µm.

$$D=\\frac{n}{\\overline{{d }\_{g}}}{\\left(\\frac{{d}\_{g}}{\\overline{{d }\_{g}}}\\right)}^{n}{e}^{{-\\left(\\frac{d}{{d}\_{g}}\\right)}^{n}} ; n=8 , \\overline{{d }\_{g}}=80\\mathrm{ \\mu m}$$

(8)


where \\(D\\) is the accumulated fraction of particles (μm) in the range of \\(d\\) (10 to 300 µm). \\(n\\) is the shape parameter, \\({d}\_{g}\\) is the consider diameter (μm) and \\(\\overline{{d }\_{g}}\\) is the mean diameter (μm).

The Taylor analogy breakup (TAB) rupture model was implemented to provide a solution to particle distortion and breakup. In addition, the turbulent particle dispersion with the exact eddy interaction time is considered. A quasi-stable model was implemented to address the phenomenon of evaporation. The droplets lose mass \\({\\dot{m}}\_{p}\\) (g/s) according to the following formula, Busco et al.[28](https://www.nature.com/articles/s41598-024-57425-z#ref-CR28 "Busco, G., Yang, S. R., Seo, J. & Hassan, Y. A. Sneezing and asymptomatic virus transmission. Phys. Fluids 32, 073309.                    https://doi.org/10.1063/5.0019090                                     (2020).") and Ugarte-Anero et al.[15](https://www.nature.com/articles/s41598-024-57425-z#ref-CR15 "Ugarte-Anero, A., Fernandez-Gamiz, U., Portal-Porras, K., Zulueta, E. & Urbina-Garcia, O. Computational characterization of the behavior of a saliva droplet in a social environment. Sci. Rep. 12, 6405.                    https://doi.org/10.1038/s41598-022-10180-5                                     (2022).")

$${\\dot{m}}\_{p}={{\\text{g}}}^{\*}\\times {A}\_{s}{\\text{ln}}\\left(1+B\\right)$$

(9)


where \\({{\\text{g}}}^{\*}\\) is the mass transfer conductance (g/m2s) and \\({A}\_{s}\\) is the droplet surface area (m2). \\(B\\) is the spacing transfer number.

Droplet motion was calculated using the Newton’s second law. The drag force (N), presented in Eq. ( [9](https://www.nature.com/articles/s41598-024-57425-z#Equ9)), is calculated by the applied forces on a droplet as a function of its relative velocity inside the Eulerian phase. To obtain the drag force, the Schiller–Nauman correlation was employed ( [9](https://www.nature.com/articles/s41598-024-57425-z#Equ9)).

$${F}\_{D}=1/2{C}\_{D}\\uprho {A}\_{P}{V}\_{rel}^{2}$$

(10)


where \\({C}\_{D}\\) is the drag coefficient, \\(\\uprho \\) is the density of air (kg/m3), \\({A}\_{P}\\) is the projected area of the droplet (m2) and \\({V}\_{rel}\\) is the relative velocity (m/s). The expression for calculating the drag coefficient is as follows:

$${{\\text{C}}}\_{{\\text{d}}}\\left\\{\\begin{array}{ll}\\frac{24}{{\\text{Re}}}, & \\quad Re\\le 1\\\ \\frac{24}{{\\text{Re}}}\\left(1+0.15{{\\text{Re}}}^{0.687}\\right), & \\quad 1 < Re\\le 1000\\\ 0.44, & \\quad Re>1000\\end{array}\\right.$$

(11)


where Re is the Reynolds number.

In addition, the gravitational force was also considered. Although the drag force is preeminent at the first moment from the start of the cough, when the cough is stopped, the buoyancy, gravity, the pressure gradient force and streams affect the droplet path.

As a droplet dispersion study, this was a classical unsteady problem. To solve this problem, the Courant number (\\(Co\\)) needed to be define and is shown in Eq. ( [10](https://www.nature.com/articles/s41598-024-57425-z#Equ10)); this dimensionless number relates how many cells traverse a parcel or a droplet at each time step, \\(\\Delta t\\) (s), for a known velocity, \\(v\\) (m/s). \\(\\Delta x\\) (m) represented the length interval.

$$Co=\\frac{v\\cdot \\Delta t}{\\Delta x}$$

(12)


To obtain an accurate solution, the Co needs to be equal or below to 1. The smallest cell (attached to the mouth cell) had a thickness of \\(\\Delta x=5\\) mm and the maximum obtained velocities were 4.4 m/s during breathing and 17.7 m/s during coughing; thus, Eq. ( [10](https://www.nature.com/articles/s41598-024-57425-z#Equ10)) was used to determine that the selected values at \\(\\Delta t=0.001\\) s for the breathing period and at \\(\\Delta t=2.3\\cdot {10}^{-4}\\) s for the coughing phase (from second 5 to second 5.5) were valid to produce an accurate result.

The commercial CFD code STAR-CCM + v.14.02 (Siemens, London, UK) were used to define and solve the numerical problems that were defined to study CO2 accumulation and droplet dispersion. A personal server-clustered parallel computer with an Intel Xeon © E5-2609 v2 CPU @ 2.5 GHz (16 cores) and 45 GB of RAM was used to run all simulations.

### Validation

A mathematical model based on computational fluid techniques needed to be validated with the experimental results, and similar results were obtained. Therefore, an experimental study was selected. For this purpose, the phenomenon of evaporation was observed by studying the reduction in the diameter of the droplet. The predicted results from Rand and Marshall (1952) were consistent with the obtained results. This investigation investigated the evaporation of stationary water droplets in a dry environment (T∞ = 25 °C, RH = 0%). The initial temperature of the droplet is 9 °C. Figure [6](https://www.nature.com/articles/s41598-024-57425-z#Fig6) shows a comparison of the experimental data, the data from the model of Wang et al.[67](https://www.nature.com/articles/s41598-024-57425-z#ref-CR67 "Wang, B., Wu, H. & Wan, X.-F. Transport and fate of human expiratory droplets—a modeling approach. Phys. Fluids 32, 083307.                    https://doi.org/10.1063/5.0021280                                     (2020)."), the data from Xie et al.[39](https://www.nature.com/articles/s41598-024-57425-z#ref-CR39 "Xie, X., Li, Y., Chwang, A. T. Y., Ho, P. L. & Seto, W. H. How far droplets can move in indoor environments? Revisiting the wells evaporation? Falling curve. Indoor Air 17, 211–225.                    https://doi.org/10.1111/j.1600-0668.2007.00469.x                                     (2007)."), and the data obtained with the designed configuration.

**Figure 6**

![Figure 6](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig6_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/6)

Comparison of the data collected with the designed configuration and other investigations, such as the experimental results from Ranz and Marshall[72](https://www.nature.com/articles/s41598-024-57425-z#ref-CR72 "Ranz, W. & Marshall, W. Evaporation from drops. Chem. Eng. Prog. 48, 141–146 (1952).") and the numerical results from Wang et al.[67](https://www.nature.com/articles/s41598-024-57425-z#ref-CR67 "Wang, B., Wu, H. & Wan, X.-F. Transport and fate of human expiratory droplets—a modeling approach. Phys. Fluids 32, 083307.                    https://doi.org/10.1063/5.0021280                                     (2020).") and Xie et al.[39](https://www.nature.com/articles/s41598-024-57425-z#ref-CR39 "Xie, X., Li, Y., Chwang, A. T. Y., Ho, P. L. & Seto, W. H. How far droplets can move in indoor environments? Revisiting the wells evaporation? Falling curve. Indoor Air 17, 211–225.                    https://doi.org/10.1111/j.1600-0668.2007.00469.x                                     (2007).").

## Results

### CO2 concentration

Figure [7](https://www.nature.com/articles/s41598-024-57425-z#Fig7) shows the increase in the CO2 concentration measured in mass parts per million (ppm) during the 15 s journey. The unique CO2 source was the person coughing, who expelled CO2 with other gases in a sinusoidal breathing shape. In the NF case, an increase in CO2 had a pure sinusoidal accumulative shape, reaching a maximum value of 35 ppm in 15 s; this occurred at the instant when the simulation finished. For cases where ventilation existed, the concentration was lower than that in the case of NF for the entire time, with the exception of the first second of the UF case, where the concentration was unexpectedly higher than that in the case of no ventilation.

**Figure 7**

![Figure 7](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig7_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/7)

CO2 concentration inside the lift. Red line: no fan; blue line: upwards-blowing case; green line: downwards-blowing case.

The incidence of ventilation was slightly different among the two groups. Since the CO2 total expulsion was triggered in three cycles in the first two cycles, the UF case had the highest increasing ratio. In contrast, the decrease in the CO2 concentration observed in the moments where breathing process was in aspiration phase were similar for both ventilated cases. At the 13th second, the CO2 exhausting stream was established for UF case. This was likely due to the minimal increase in the last exhaust cycle for the UF case compared to that for the DF case. In the last second, both ventilation systems reached the same value of 20.2 ppm. Interestingly, the no fan and downwards-blowing fan cases were totally cyclic and harmonious, while the upward-blowing fan case had few irregularities, and the cycles were not homogenous.

For more information, see the [supplementary material](https://www.nature.com/articles/s41598-024-57425-z#MOESM1), where CO2 transport was modelled and studied.

### CO2-based infection probability

Equation ( [11](https://www.nature.com/articles/s41598-024-57425-z#Equ11)) describes a validated solution presented in Wang et al.[68](https://www.nature.com/articles/s41598-024-57425-z#ref-CR68 "Wang, Z., Galea, E. R., Grandison, A., Ewer, J. & Jia, F. A coupled computational fluid dynamics and Wells-Riley model to predict COVID-19 infection probability for passengers on long-distance trains. Saf. Sci. 147, 105572.                    https://doi.org/10.1016/j.ssci.2021.105572                                     (2022).") and Foster and Kinzel[69](https://www.nature.com/articles/s41598-024-57425-z#ref-CR69 "Foster, A. & Kinzel, M. Estimating COVID-19 exposure in a classroom setting: A comparison between mathematical and numerical models. Phys. Fluids 33, 021904.                    https://doi.org/10.1063/5.0040755                                     (2021).") to calculate the probability of infection in a closed space. This equation depends on the emitted quanta, which is the number of contagious aerosols emitted per hour, with one quantum being the necessary amount to be infected. Additionally, the emitted quanta depend on the CO2 concentration and exposure time. For this study, a 20-quantum per hour emission rate was estimated based on the proposed values of[68](https://www.nature.com/articles/s41598-024-57425-z#ref-CR68 "Wang, Z., Galea, E. R., Grandison, A., Ewer, J. & Jia, F. A coupled computational fluid dynamics and Wells-Riley model to predict COVID-19 infection probability for passengers on long-distance trains. Saf. Sci. 147, 105572.                    https://doi.org/10.1016/j.ssci.2021.105572                                     (2022).") and[69](https://www.nature.com/articles/s41598-024-57425-z#ref-CR69 "Foster, A. & Kinzel, M. Estimating COVID-19 exposure in a classroom setting: A comparison between mathematical and numerical models. Phys. Fluids 33, 021904.                    https://doi.org/10.1063/5.0040755                                     (2021)."), who implemented 14 and 100 quantum per hour, respectively.

$$P=1-{e}^{(-q\\cdot Y\\cdot t)}$$

(13)


where \\({\\text{P}}\\) is the probability of being infected, \\({\\text{q}}\\) is the quanta emission rate (h−1), \\({\\text{Y}}\\) is the CO2 concentration over time (ppm) and \\({\\text{t}}\\) is the exposure time (h).

Figure [8](https://www.nature.com/articles/s41598-024-57425-z#Fig8) shows the calculated probability of contagion for the proposed scenarios for the entire time period based on Eq. ( [11](https://www.nature.com/articles/s41598-024-57425-z#Equ11)). Along 15 s, the no fan case was always the riskiest scenario; the CO2 concentration increased, reaching a maximum probability of COVID-19 infection of 94.5%. The values for the upwards-blowing fan case and downwards-blowing fan case were similar until the 7th second; here, the upwards blowing fan case increased slightly more than downwards blowing fan case, at around 12% until 12.5th second. Beyond this moment, both probabilities converged to similar values of 80.6% for the upwards-blowing fan case and 81.2% for the downwards-blowing fan case in the last second. For three scenarios, the increase in risk was linked to CO2 exhalation in higher amounts rather than to the exposure time. The differences in the gradients between the exhalation moments and inhalation moments were apparent.

**Figure 8**

![Figure 8](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig8_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/8)

CO2-based infection probability. Red line: no fan; blue line: upwards-blowing case; green line: downwards-blowing case.

### Droplet quantity fraction

Figure [9](https://www.nature.com/articles/s41598-024-57425-z#Fig9) shows that the droplets missing from the domain are expressed as a fraction of 1. In three cases, droplets appeared suddenly in the 5th second. The graph indicates that the DF case largely differed from the UF case and the NF case. According to the image, in the downwards-blowing fan case, 30% of the droplets evaporated or were quickly expelled in one and a half seconds, respectively, and the removal was noticeable from the first moment. Instead, the upwards-blowing case needed two seconds to eliminate only 10% of the droplets; moreover, no fan case lasted 2.4 s to evaporate the same quantity of droplets. In the UF and NF cases, the removal started 1 s and 1.5 s, respectively, after the cough began.

**Figure 9**

![Figure 9](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig9_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/9)

Droplets fraction inside the lift. Red line: no fan; blue line: upwards-blowing case; green line: downwards-blowing case.

Ninety percent of the droplets were removed within 3.5 s from the beginning of the cough in the DF case. This time was delayed to 4.5 s for both the NF and UF cases. On the other hand, the total quantity of evaporated or expelled droplets occurred approximately at the same time for the three cases, in 5.6 s for the NF case and 6 s for the two cases with ventilation.

Finally, some differences between elimination ratios were detected. In the DF case, droplets were removed in two negative exponential frames, while in the UF and NF cases, droplets were removed in a parabolic form. Table [5](https://www.nature.com/articles/s41598-024-57425-z#Tab5) provides the fitting equations and main parameters such as the confidence bound, R2 and the root mean squared error (RMSE). Equations were proposed presuming that the cough started at second 0. The plotted results can be found in Fig. [10](https://www.nature.com/articles/s41598-024-57425-z#Fig10).

**Table 5 Fitting equations and parameters.**

[Full size table](https://www.nature.com/articles/s41598-024-57425-z/tables/5)

**Figure 10**

![Figure 10](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig10_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/10)

Comparison of droplet fractions between CFD results (solid lines) and predicted results from Table [5](https://www.nature.com/articles/s41598-024-57425-z#Tab5) (blurred lines). Red line: No fan case; blue line: upwards blowing case; green line: downwards blowing case.

### Droplet dispersion

In this subsection, the propagation of droplets for different ventilation systems was visually compared. The defined images were chosen for three phases, where the total exhalation, a well-expanded dispersion and, finally, the last remaining droplets were well defined. According to this proposition, the 6th second, 8th second and 10th second were projected (the cough started in second 5). The same time-configuration was adopted for all ventilation strategies, making it possible to compare them and evaluate which was the optimal set up in terms of dispersion. Frontal and perspective images are presented for a better comprehension of the volume dispersion.

Figure [11](https://www.nature.com/articles/s41598-024-57425-z#Fig11) shows the results for the no fan case. The entire droplet cloud was observed outside the mouth at a few centimetres below the mouth in the 6th second. Two seconds later, the cloud continued to fall due to gravity and was slowed by drag and buoyancy. During this time, the particles decreased in size and number due to evaporation. In the last second, very few particles remained inside the domain according to the height of the subject’s waist. For this no-fan case, the unique horizontal displacement was due to the initial cough jet. Once the drag balanced the displacement in this axis, no force was able to move any particle.

**Figure 11**

![Figure 11](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig11_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/11)

Droplet dispersion inside the lift for the no fan case. ( **a**) and ( **d**) in 6th second; ( **b**) and ( **e**) in 8th second; ( **c**) and ( **f**) in 10th second. First row of images for frontal point view. Second image row for perspective point view.

Figure [12](https://www.nature.com/articles/s41598-024-57425-z#Fig12) shows the results for the upwards-blowing fan case. The droplets travelled forward the first moment from the beginning of the cough. Immediately, they were attracted by the exhausting stream but inside a recirculation behaviour that positioned them at the back of the emitter and at his left side. In this case, several particles maintained a high position over the head of the infected person. No droplet reached the second occupant due to the mentioned recirculation. Particles near the exhausting fan disappeared before being expelled due to evaporation.

**Figure 12**

![Figure 12](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig12_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/12)

Droplet dispersion inside the lift for the upwards-blowing fan case. ( **a**) and ( **d**) in 6th second; ( **b**) and ( **e**) in 8th second; ( **c**) and ( **f**) in 10th second. First row of images for frontal point view. Second image row for perspective point view.

Figure [13](https://www.nature.com/articles/s41598-024-57425-z#Fig13) shows the downwards-blowing fan performance. The pictures explain the induced movements on the droplets. From the beginning, the particles moved downwards rapidly, quickly impacting on the bottom surface and becoming attached there. Few particles entered recirculation and were capable of going up after passing through the stream without being stuck on the floor or evaporated, reaching positions near the second occupant. For this case, the dispersion could be considered total but at a low level; most of the particles evaporated quickly, but few particles reached positions far away from the source in all Cartesian axes.

**Figure 13**

![Figure 13](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_Fig13_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-024-57425-z/figures/13)

Droplet dispersion inside the lift for the downwards-blowing fan case. ( **a**) and ( **d**) in 6th second; ( **b**) and ( **e**) in 8th second; ( **c**) and ( **f**) in 10th second. First row of images for frontal point view. Second image row for perspective point view.

## Discussion and study limitations

The presented CFD study is applicable to a possible but poorly likely scenario in which two subjects face each other and share a clinical lift where one of them coughs. Additionally, it is noticeable that only the person coughing exhaled CO2. The purpose of this hypothesis was to investigate the airborne concentration coming from the infected person. Carbon dioxide concentrations were measured in mass ppm, and the initial concentration was zero.

The simplification of generating a circular hole with negative pressure (downwards-blowing fan case) or velocity inlet (upwards-blowing fan case) could alter the real results. The simulated case does not generate the typical helical streams of a fan. Nevertheless, according to Shinohara et al.[50](https://www.nature.com/articles/s41598-024-57425-z#ref-CR50 "Shinohara, N. et al. Air exchange rates and advection-diffusion of CO2 and aerosols in a route bus for evaluation of infection risk. Indoor Air                    https://doi.org/10.1111/ina.13019                                     (2022)."), this approximation is valid for accurately calculating the CO2 concentration but not for calculating the gas mixing homogeneity inside the domain due to the lack of turbulence. The supply of air has an important effect on interactions with respiratory flows. For the DF case, the effect of the supply air was immediate since the flow directly affected the CO2 emission and droplet dispersion. However, for the UF case, the renewed air did not quickly affect either the gas or droplet emissions. For this case, the supply air entered from below and crossed a large horizontal area until it reached the top; thus, the effect was not centred if not near the wall positioned in the face of the racks.

According to the obtained CO2 concentration results, the maximum obtained value was 35 ppm in the no fan case. In contrast, downwards-blowing fan ventilation appears to be the most suitable approach. This result can be debateable because the exhaust area is less than that in the upwards-blowing fan case (0.045 m2 < 0.07 m2). However, this result was reported by Rodriguez et al.[11](https://www.nature.com/articles/s41598-024-57425-z#ref-CR11 "Rodríguez, D., Urbieta, I. R., Velasco, Á., Campano-Laborda, M. Á. & Jiménez, E. Assessment of indoor air quality and risk of covid-19 infection in Spanish secondary school and university classrooms. Build. Environ. 226, 109717.                    https://doi.org/10.1016/j.buildenv.2022.109717                                     (2022)."), whose recommendation was to set up the inlet supply air at the top and the outlet at the bottom. This result could differ from the 15th second onwards, when the two proposed ventilation setups coincided at 20.2 ppm, and immediately after, the upwards-blowing fan values were lower than those of the downwards-blowing fan case. Considering the results, the study could be expanded to longer time frames. The results show a unique value for the entire computational domain volume. In future works, the authors recommend discretizing the elevator domain into different height-volume controls to identify the riskiest zones.

The ability of droplets to be removed was evaluated fractionally. Droplets appeared immediately (in 0.23 s). The evaporation, deposition or expulsion data affirmed that the downwards-blowing fan had the best performance. In contrast, the no fan case took the longest to start eliminating droplets. In these terms, the upwards-blowing fan case had slightly greater effectiveness than the no ventilation setup. Notably, 100% of the droplets nearly disappeared at the same time, between 5.6 and 6.1 s after the start of coughing, which was consistent with the results of Yang et al.[10](https://www.nature.com/articles/s41598-024-57425-z#ref-CR10 "Yang, X. et al. Transmission of pathogen-laden expiratory droplets in a coach bus. J. Hazard. Mater. 397, 122609.                    https://doi.org/10.1016/j.jhazmat.2020.122609                                     (2020)."). In addition, aerosols are composed of different components that form the fluid of saliva, according to Carpenter et al.[70](https://www.nature.com/articles/s41598-024-57425-z#ref-CR70 "Carpenter, G. H. The secretion, components, and properties of saliva. Annu. Rev. Food Sci. Technol. 4, 267–276.                    https://doi.org/10.1146/annurev-food-030212-182700                                     (2013)."). This fluid is formed by water and nonvolatile solids[71](https://www.nature.com/articles/s41598-024-57425-z#ref-CR71 "Nicas, M., Nazaroff, W. W. & Hubbard, A. Toward understanding the risk of secondary airborne infection: Emission of respirable pathogens. J. Occup. Environ. Hyg. 2, 143–154.                    https://doi.org/10.1080/15459620590918466                                     (2005)."). The particles generated by the subjects of this study were simulated as pure water, as in the CFD study of Dbouk et al.[59](https://www.nature.com/articles/s41598-024-57425-z#ref-CR59 "Dbouk, T. & Drikakis, D. On coughing and airborne droplet transmission to humans. Phys. Fluids 32, 053310.                    https://doi.org/10.1063/5.0011960                                     (2020)."). The software used has the limitation of not being able to simulate the nonvolatile solid components of the fluid. Therefore, the particles created for this study evaporated completely when they lost all the liquid and were removed from the domain. This is not entirely true since nonvolatile components that can contain viruses would still exist in the environment. Thus, it is necessary to know that the results shown in this research do not reveal aerosols with volatile components but rather reveal aerosols with liquids.

Four linear regressions were proposed (2 for the downwards-blowing fan case, 1 for the upwards-blowing fan case and 1 for the no fan case data). The variability of \\({R}^{2}\\) for the proposed equations was sufficiently accurate (between 0.9528 and 0.9954). These values are not representative of the different cases presented here. Therefore, it would be recommended and interesting to perform tests with different variables, such as different relative humidities, droplet emission sources, ventilation setups, and ventilation ratios. This information could be a useful tool or database for studying and predicting better ventilation systems in small closed spaces.

In relation to the ventilation performance under droplet dispersion, it was remarkable that the safest scenario could be the strategy without mechanical ventilation. The dispersion in the no fan case was the smallest in comparison with that in the other two cases. This was because the unique propagation forces were due to the initial cough jet. When this puff finished, the droplets fell down vertically by gravitational force with the unique opposition of the air drag force. In this case, the healthy passenger was safe from direct contagion. The upwards-blowing fan case had greater dispersion, but the droplets were concentrated above all in the emitter region. The recirculation caused by the fan maintained particles near the origin zone, making the area of the healthy subject relatively safe in terms of direct infection. Finally, the downwards blowing fan quickly impacted most of the droplets on the floor, removing them from the domain. The issue in this scenario was that a few particles could avoid collision, recirculate inside the lift and even increase the healthy passenger respiration volume, facilitating direct infection.

## Conclusion

In the present study, 3 CFD cases were compared. A lift under a typical clinical atmosphere and standard size, with two standing subjects, was modelled. Both breathed in a sinusoidal shape, but only one (the infected person) exhaled CO2. After 5 s, the infected person coughed, and the droplets were released into the air. Three scenarios were compared: without ventilation, with an upwards-blowing fan, and with a downwards-blowing fan. Finally, the mass CO2 concentration, the amount of cough particles removed and droplets dispersion were compared and analysed for the different ventilation cases. The results showed the following:

- The no ventilation case was less effective at exhausting CO2, reaching 35 ppm in 15 s. The downwards-blowing fan case expelled the most gas. Similar conclusions were drawn from the risk probability study. The no ventilation case was associated with a higher contagion rate; moreover, it was difficult to conclude that downwards-blowing ventilation case was safer than the upwards-blowing fan case.

- With respect to droplet deletion, the best case was a downwards-blowing fan system, which removed all droplets more quickly. However, the other two cases exhibited similar trends with the upwards-blowing fan configuration being slightly more effective.

- Linear regressions were developed to adjust the obtained results to simple mathematical models, and a minimum acceptable precision of \\({R}^{2}\\)= 0.9528 was obtained.

- In terms of liquid droplet dispersion, the no ventilation scenario appeared to be the safest. All droplets fell down and evaporated before reaching the floor.


## Data availability

The data presented in this study are available upon request from the corresponding author.

## Abbreviations

Ap
:

Projected area of the droplet \[m2\]

As
:

Droplet surface area \[m2\]

\\(B\\)
:

Spacing transfer number \[–\]

\\({C}\_{D}\\)
:

Drag coefficient \[–\]

\\(Co\\)
:

Courant number \[–\]

\\(D\\)
:

Accumulated fraction of particles \[μm\]

d:

Diameter range \[μm\]

\\({d}\_{g}\\)
:

Consider diameter \[μm\]

\\(\\overline{{d }\_{g}}\\)
:

Mean diameter \[μm\]

\\({F}\_{D}\\)
:

Drag force \[N\]

\\({{\\text{g}}}^{\*}\\)
:

Mass transfer conductance \[g/m2s\]

\\({\\dot{m}}\_{p}\\)
:

Mass of droplets \[g/s\]

\\(n\\)
:

Shape parameter \[–\]

\\(p\\)
:

Order of converge \[–\]

\\({\\text{P}}\\)
:

Probability of risk of infection \[–\]

\\({\\text{q}}\\)
:

Quanta emission rate \[h−1\]

\\(r\\)
:

Mesh refinement ratio \[–\]

Re:

Reynolds number \[–\]

\\({\\text{t}}\\)
:

Exposure time \[h\]

T∞
:

Environment temperature \[°C\]

\\(v\\)
:

Velocity \[m/s\]

\\({V}\_{ax}\\)
:

Axial velocity \[m/s\]

\\({V}\_{rel}\\)
:

Relative velocity \[m/s\]

\\({\\text{Y}}\\)
:

CO2 concentration over time \[ppm\]

\\(\\Delta t\\)
:

Time step \[t\]

\\(\\Delta x\\)
:

Length interval \[m\]

\\(\\in \\)
:

Relative error \[–\]

\\(\\uprho \\)
:

Density \[kg/m3\]

Length:

Meter \[m\]

Area (Length2):

Square meter \[m2\]

Volume (Length3):

Cubic meter \[m3\]

Mass:

Gram \[g\]

Time:

Second \[s\]

Temperature:

Celsius \[°C\]

Velocity (Length/Time):

Meter/second \[m/s\]

Volume :

Parts per million \[ppm\]

Volume/Time:

Flow \[Litre/minute\]

Pressure:

Pascal \[Pa\]

Force:

Kilogram × meter/square second \[N\]

CFD:

Computational fluid dynamics

CO2
:

Carbon dioxide

DF:

Downwards blowing ventilation

EN:

European standards

GCI:

Grid converge index

NF:

Without ventilation

RANS:

Reynolds averaged Navier–Stokes

RH:

Relative humidity

RMSE:

Root mean squared error

TAB:

Taylor analogy breakup

UF:

Upwards blowing ventilation

VC:

Volume control

RANS:

Reynolds averaged Navier Stokes

## References

01. Roychoudhury, S. _et al._ Viral pandemics of twenty-first century. _J. Microb. Biotech. Food Sci_ **10**, 711–716. [https://doi.org/10.15414/jmbfs.2021.10.4.711-716](https://doi.org/10.15414/jmbfs.2021.10.4.711-716) (2021).

    [Article](https://doi.org/10.15414%2Fjmbfs.2021.10.4.711-716) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXpvVOqs70%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Viral%20pandemics%20of%20twenty-first%20century&journal=J.%20Microb.%20Biotech.%20Food%20Sci&doi=10.15414%2Fjmbfs.2021.10.4.711-716&volume=10&pages=711-716&publication_year=2021&author=Roychoudhury%2CS&author=Das%2CA&author=Sengupta%2CP&author=Dutta%2CS&author=Roychoudhury%2CS&author=Kolesarova%2CA&author=Hleba%2CL&author=Massanyi%2CP&author=Slama%2CP)

02. _The COVID-19 Pandemic: A Wake-up Call for Better Cooperation at the Science–Policy–Society Interface_, vol. 62 (UN Department of Economic and Social Affairs (DESA) Policy Briefs, 2020).

03. Tellier, R., Li, Y., Cowling, B. J. & Tang, J. W. Recognition of aerosol transmission of infectious agents: A commentary. _BMC Infect. Dis._ **19**, 101\. [https://doi.org/10.1186/s12879-019-3707-y](https://doi.org/10.1186/s12879-019-3707-y) (2019).

    [Article](https://link.springer.com/doi/10.1186/s12879-019-3707-y) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=30704406) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC6357359) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Recognition%20of%20aerosol%20transmission%20of%20infectious%20agents%3A%20A%20commentary&journal=BMC%20Infect.%20Dis.&doi=10.1186%2Fs12879-019-3707-y&volume=19&publication_year=2019&author=Tellier%2CR&author=Li%2CY&author=Cowling%2CBJ&author=Tang%2CJW)

04. Asadi, S. _et al._ Aerosol emission and superemission during human speech increase with voice loudness. _Sci. Rep._ **9**, 2348\. [https://doi.org/10.1038/s41598-019-38808-z](https://doi.org/10.1038/s41598-019-38808-z) (2019).

    [Article](https://doi.org/10.1038%2Fs41598-019-38808-z) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2019NatSR...9.2348A) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=30787335) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC6382806) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Aerosol%20emission%20and%20superemission%20during%20human%20speech%20increase%20with%20voice%20loudness&journal=Sci.%20Rep.&doi=10.1038%2Fs41598-019-38808-z&volume=9&publication_year=2019&author=Asadi%2CS&author=Wexler%2CAS&author=Cappa%2CCD&author=Barreda%2CS&author=Bouvier%2CNM&author=Ristenpart%2CWD)

05. Leung, N. H. L. _et al._ Respiratory virus shedding in exhaled breath and efficacy of face masks. _Nat. Med._ **26**, 676–680. [https://doi.org/10.1038/s41591-020-0843-2](https://doi.org/10.1038/s41591-020-0843-2) (2020).

    [Article](https://doi.org/10.1038%2Fs41591-020-0843-2) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXmsVWjs78%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32371934) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8238571) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Respiratory%20virus%20shedding%20in%20exhaled%20breath%20and%20efficacy%20of%20face%20masks&journal=Nat.%20Med.&doi=10.1038%2Fs41591-020-0843-2&volume=26&pages=676-680&publication_year=2020&author=Leung%2CNHL&author=Chu%2CDKW&author=Shiu%2CEYC&author=Chan%2CK-H&author=McDevitt%2CJJ&author=Hau%2CBJP&author=Yen%2CH-L&author=Li%2CY&author=Ip%2CDKM&author=Peiris%2CJSM)

06. van Doremalen, N. _et al._ Aerosol and surface stability of SARS-CoV-2 as compared with SARS-CoV-1. _N. Engl. J. Med._ **382**, 1564–1567. [https://doi.org/10.1056/NEJMc2004973](https://doi.org/10.1056/NEJMc2004973) (2020).

    [Article](https://doi.org/10.1056%2FNEJMc2004973) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32182409) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Aerosol%20and%20surface%20stability%20of%20SARS-CoV-2%20as%20compared%20with%20SARS-CoV-1&journal=N.%20Engl.%20J.%20Med.&doi=10.1056%2FNEJMc2004973&volume=382&pages=1564-1567&publication_year=2020&author=Doremalen%2CN&author=Bushmaker%2CT&author=Morris%2CDH&author=Holbrook%2CMG&author=Gamble%2CA&author=Williamson%2CBN&author=Tamin%2CA&author=Harcourt%2CJL&author=Thornburg%2CNJ&author=Gerber%2CSI)

07. Morawska, L. _et al._ How can airborne transmission of COVID-19 indoors be minimised?. _Environ. Int._ **142**, 105832\. [https://doi.org/10.1016/j.envint.2020.105832](https://doi.org/10.1016/j.envint.2020.105832) (2020).

    [Article](https://doi.org/10.1016%2Fj.envint.2020.105832) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhtFWktLbM) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32521345) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7250761) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=How%20can%20airborne%20transmission%20of%20COVID-19%20indoors%20be%20minimised%3F&journal=Environ.%20Int.&doi=10.1016%2Fj.envint.2020.105832&volume=142&publication_year=2020&author=Morawska%2CL&author=Tang%2CJW&author=Bahnfleth%2CW&author=Bluyssen%2CPM&author=Boerstra%2CA&author=Buonanno%2CG&author=Cao%2CJ&author=Dancer%2CS&author=Floto%2CA&author=Franchimon%2CF)

08. Kumar, S. & King, M. D. Numerical investigation on indoor environment decontamination after sneezing. _Environ. Res._ **213**, 113665\. [https://doi.org/10.1016/j.envres.2022.113665](https://doi.org/10.1016/j.envres.2022.113665) (2022).

    [Article](https://doi.org/10.1016%2Fj.envres.2022.113665) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38XhsFersbbM) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=35714690) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9197796) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Numerical%20investigation%20on%20indoor%20environment%20decontamination%20after%20sneezing&journal=Environ.%20Res.&doi=10.1016%2Fj.envres.2022.113665&volume=213&publication_year=2022&author=Kumar%2CS&author=King%2CMD)

09. Bahramian, A., Mohammadi, M. & Ahmadi, G. Effect of indoor temperature on the velocity fields and airborne transmission of sneeze droplets: An experimental study and transient CFD modeling. _Sci. Total Environ._ **858**, 159444\. [https://doi.org/10.1016/j.scitotenv.2022.159444](https://doi.org/10.1016/j.scitotenv.2022.159444) (2023).

    [Article](https://doi.org/10.1016%2Fj.scitotenv.2022.159444) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2023ScTEn.858o9444B) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38XivVOns7fN) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=36252673) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Effect%20of%20indoor%20temperature%20on%20the%20velocity%20fields%20and%20airborne%20transmission%20of%20sneeze%20droplets%3A%20An%20experimental%20study%20and%20transient%20CFD%20modeling&journal=Sci.%20Total%20Environ.&doi=10.1016%2Fj.scitotenv.2022.159444&volume=858&publication_year=2023&author=Bahramian%2CA&author=Mohammadi%2CM&author=Ahmadi%2CG)

10. Yang, X. _et al._ Transmission of pathogen-laden expiratory droplets in a coach bus. _J. Hazard. Mater._ **397**, 122609\. [https://doi.org/10.1016/j.jhazmat.2020.122609](https://doi.org/10.1016/j.jhazmat.2020.122609) (2020).

    [Article](https://doi.org/10.1016%2Fj.jhazmat.2020.122609) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXosV2gs7g%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32361671) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7152903) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Transmission%20of%20pathogen-laden%20expiratory%20droplets%20in%20a%20coach%20bus&journal=J.%20Hazard.%20Mater.&doi=10.1016%2Fj.jhazmat.2020.122609&volume=397&publication_year=2020&author=Yang%2CX&author=Ou%2CC&author=Yang%2CH&author=Liu%2CL&author=Song%2CT&author=Kang%2CM&author=Lin%2CH&author=Hang%2CJ)

11. Rodríguez, D., Urbieta, I. R., Velasco, Á., Campano-Laborda, M. Á. & Jiménez, E. Assessment of indoor air quality and risk of covid-19 infection in Spanish secondary school and university classrooms. _Build. Environ._ **226**, 109717\. [https://doi.org/10.1016/j.buildenv.2022.109717](https://doi.org/10.1016/j.buildenv.2022.109717) (2022).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2022.109717) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=36313012) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9595429) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Assessment%20of%20indoor%20air%20quality%20and%20risk%20of%20covid-19%20infection%20in%20Spanish%20secondary%20school%20and%20university%20classrooms&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2022.109717&volume=226&publication_year=2022&author=Rodr%C3%ADguez%2CD&author=Urbieta%2CIR&author=Velasco%2C%C3%81&author=Campano-Laborda%2CM%C3%81&author=Jim%C3%A9nez%2CE)

12. Ahmadzadeh, M. & Shams, M. Passenger exposure to respiratory aerosols in a train cabin: Effects of window, injection source, output flow location. _Sustain. Cities Soc._ **75**, 103280\. [https://doi.org/10.1016/j.scs.2021.103280](https://doi.org/10.1016/j.scs.2021.103280) (2021).

    [Article](https://doi.org/10.1016%2Fj.scs.2021.103280) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34580621) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8459195) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Passenger%20exposure%20to%20respiratory%20aerosols%20in%20a%20train%20cabin%3A%20Effects%20of%20window%2C%20injection%20source%2C%20output%20flow%20location&journal=Sustain.%20Cities%20Soc.&doi=10.1016%2Fj.scs.2021.103280&volume=75&publication_year=2021&author=Ahmadzadeh%2CM&author=Shams%2CM)

13. Jiang, G., Li, F. & Hu, T. Transport characteristics and transmission risk of virus-containing droplets from coughing in outdoor windy environment. _Toxics_ **10**, 294\. [https://doi.org/10.3390/toxics10060294](https://doi.org/10.3390/toxics10060294) (2022).

    [Article](https://doi.org/10.3390%2Ftoxics10060294) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38Xhs1ylu7rF) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=35736903) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9230890) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Transport%20characteristics%20and%20transmission%20risk%20of%20virus-containing%20droplets%20from%20coughing%20in%20outdoor%20windy%20environment&journal=Toxics&doi=10.3390%2Ftoxics10060294&volume=10&publication_year=2022&author=Jiang%2CG&author=Li%2CF&author=Hu%2CT)

14. Zhang, Y. _et al._ Distribution of droplet aerosols generated by mouth coughing and nose breathing in an air-conditioned room. _Sustain. Cities Soc._ **51**, 101721\. [https://doi.org/10.1016/j.scs.2019.101721](https://doi.org/10.1016/j.scs.2019.101721) (2019).

    [Article](https://doi.org/10.1016%2Fj.scs.2019.101721) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Distribution%20of%20droplet%20aerosols%20generated%20by%20mouth%20coughing%20and%20nose%20breathing%20in%20an%20air-conditioned%20room&journal=Sustain.%20Cities%20Soc.&doi=10.1016%2Fj.scs.2019.101721&volume=51&publication_year=2019&author=Zhang%2CY&author=Feng%2CG&author=Bi%2CY&author=Cai%2CY&author=Zhang%2CZ&author=Cao%2CG)

15. Ugarte-Anero, A., Fernandez-Gamiz, U., Portal-Porras, K., Zulueta, E. & Urbina-Garcia, O. Computational characterization of the behavior of a saliva droplet in a social environment. _Sci. Rep._ **12**, 6405\. [https://doi.org/10.1038/s41598-022-10180-5](https://doi.org/10.1038/s41598-022-10180-5) (2022).

    [Article](https://doi.org/10.1038%2Fs41598-022-10180-5) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2022NatSR..12.6405U) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38XhtVaksLjL) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=35437309) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9016067) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Computational%20characterization%20of%20the%20behavior%20of%20a%20saliva%20droplet%20in%20a%20social%20environment&journal=Sci.%20Rep.&doi=10.1038%2Fs41598-022-10180-5&volume=12&publication_year=2022&author=Ugarte-Anero%2CA&author=Fernandez-Gamiz%2CU&author=Portal-Porras%2CK&author=Zulueta%2CE&author=Urbina-Garcia%2CO)

16. Zhao, Y., Feng, Y. & Ma, L. Numerical evaluation on indoor environment quality during high numbers of occupied passengers in the departure hall of an airport terminal. _J. Build. Eng._ **51**, 104276\. [https://doi.org/10.1016/j.jobe.2022.104276](https://doi.org/10.1016/j.jobe.2022.104276) (2022).

    [Article](https://doi.org/10.1016%2Fj.jobe.2022.104276) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2022usoe.book.....Z) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Numerical%20evaluation%20on%20indoor%20environment%20quality%20during%20high%20numbers%20of%20occupied%20passengers%20in%20the%20departure%20hall%20of%20an%20airport%20terminal&journal=J.%20Build.%20Eng.&doi=10.1016%2Fj.jobe.2022.104276&volume=51&publication_year=2022&author=Zhao%2CY&author=Feng%2CY&author=Ma%2CL)

17. Peng, Z. & Jimenez, J. L. Exhaled CO2 as a COVID-19 infection risk proxy for different indoor environments and activities. _Environ. Sci. Technol. Lett._ **8**, 392–397. [https://doi.org/10.1021/acs.estlett.1c00183](https://doi.org/10.1021/acs.estlett.1c00183) (2021).

    [Article](https://doi.org/10.1021%2Facs.estlett.1c00183) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXnvF2nuro%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=37566374) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Exhaled%20CO2%20as%20a%20COVID-19%20infection%20risk%20proxy%20for%20different%20indoor%20environments%20and%20activities&journal=Environ.%20Sci.%20Technol.%20Lett.&doi=10.1021%2Facs.estlett.1c00183&volume=8&pages=392-397&publication_year=2021&author=Peng%2CZ&author=Jimenez%2CJL)

18. Pastor-Fernández, A., Cerezo-Narváez, A., Montero-Gutiérrez, P., Ballesteros-Pérez, P. & Otero-Mateo, M. Use of low-cost devices for the control and monitoring of CO2 concentration in existing buildings after the COVID era. _Appl. Sci._ **12**, 3927\. [https://doi.org/10.3390/app12083927](https://doi.org/10.3390/app12083927) (2022).

    [Article](https://doi.org/10.3390%2Fapp12083927) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38XhtVyns7fL) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Use%20of%20low-cost%20devices%20for%20the%20control%20and%20monitoring%20of%20CO2%20concentration%20in%20existing%20buildings%20after%20the%20COVID%20era&journal=Appl.%20Sci.&doi=10.3390%2Fapp12083927&volume=12&publication_year=2022&author=Pastor-Fern%C3%A1ndez%2CA&author=Cerezo-Narv%C3%A1ez%2CA&author=Montero-Guti%C3%A9rrez%2CP&author=Ballesteros-P%C3%A9rez%2CP&author=Otero-Mateo%2CM)

19. Vouriot, C. V. M., Burridge, H. C., Noakes, C. J. & Linden, P. F. Seasonal variation in airborne infection risk in schools due to changes in ventilation inferred from monitored carbon dioxide. _Indoor Air_ **31**, 1154–1163. [https://doi.org/10.1111/ina.12818](https://doi.org/10.1111/ina.12818) (2021).

    [Article](https://doi.org/10.1111%2Fina.12818) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXhtlOltLnI) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=33682974) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8251097) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Seasonal%20variation%20in%20airborne%20infection%20risk%20in%20schools%20due%20to%20changes%20in%20ventilation%20inferred%20from%20monitored%20carbon%20dioxide&journal=Indoor%20Air&doi=10.1111%2Fina.12818&volume=31&pages=1154-1163&publication_year=2021&author=Vouriot%2CCVM&author=Burridge%2CHC&author=Noakes%2CCJ&author=Linden%2CPF)

20. Schade, W., Reimer, V., Seipenbusch, M. & Willer, U. Experimental investigation of aerosol and CO2 dispersion for evaluation of COVID-19 infection risk in a concert hall. _IJERPH_ **18**, 3037\. [https://doi.org/10.3390/ijerph18063037](https://doi.org/10.3390/ijerph18063037) (2021).

    [Article](https://doi.org/10.3390%2Fijerph18063037) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXhtFyitLzM) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=33809493) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8002200) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Experimental%20investigation%20of%20aerosol%20and%20CO2%20dispersion%20for%20evaluation%20of%20COVID-19%20infection%20risk%20in%20a%20concert%20hall&journal=IJERPH&doi=10.3390%2Fijerph18063037&volume=18&publication_year=2021&author=Schade%2CW&author=Reimer%2CV&author=Seipenbusch%2CM&author=Willer%2CU)

21. Zivelonghi, A. & Lai, M. Mitigating aerosol infection risk in school buildings: The role of natural ventilation, volume, occupancy and CO2 monitoring. _Build. Environ._ **204**, 108139\. [https://doi.org/10.1016/j.buildenv.2021.108139](https://doi.org/10.1016/j.buildenv.2021.108139) (2021).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2021.108139) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Mitigating%20aerosol%20infection%20risk%20in%20school%20buildings%3A%20The%20role%20of%20natural%20ventilation%2C%20volume%2C%20occupancy%20and%20CO2%20monitoring&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2021.108139&volume=204&publication_year=2021&author=Zivelonghi%2CA&author=Lai%2CM)

22. Huessler, E.-M., Hüsing, A., Vancraeyenest, M., Jöckel, K.-H. & Schröder, B. Air quality in an air ventilated fitness center reopening for pilot study during COVID-19 pandemic lockdown. _Build. Environ._ **219**, 109180\. [https://doi.org/10.1016/j.buildenv.2022.109180](https://doi.org/10.1016/j.buildenv.2022.109180) (2022).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2022.109180) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=35581988) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9098400) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Air%20quality%20in%20an%20air%20ventilated%20fitness%20center%20reopening%20for%20pilot%20study%20during%20COVID-19%20pandemic%20lockdown&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2022.109180&volume=219&publication_year=2022&author=Huessler%2CE-M&author=H%C3%BCsing%2CA&author=Vancraeyenest%2CM&author=J%C3%B6ckel%2CK-H&author=Schr%C3%B6der%2CB)

23. Yamamoto, M., Kawamura, A., Tanabe, S. & Hori, S. Predicting the infection probability distribution of airborne and droplet transmissions. _Indoor Built Environ._ [https://doi.org/10.1177/1420326X221084869](https://doi.org/10.1177/1420326X221084869) (2023).

    [Article](https://doi.org/10.1177%2F1420326X221084869) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Predicting%20the%20infection%20probability%20distribution%20of%20airborne%20and%20droplet%20transmissions&journal=Indoor%20Built%20Environ.&doi=10.1177%2F1420326X221084869&publication_year=2023&author=Yamamoto%2CM&author=Kawamura%2CA&author=Tanabe%2CS&author=Hori%2CS)

24. Lu, Y. _et al._ Affordable measures to monitor and alarm nosocomial SARS-CoV-2 infection due to poor ventilation. _Indoor Air_ **31**, 1833–1842. [https://doi.org/10.1111/ina.12899](https://doi.org/10.1111/ina.12899) (2021).

    [Article](https://doi.org/10.1111%2Fina.12899) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXhsVansLbI) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34181766) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8447035) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Affordable%20measures%20to%20monitor%20and%20alarm%20nosocomial%20SARS-CoV-2%20infection%20due%20to%20poor%20ventilation&journal=Indoor%20Air&doi=10.1111%2Fina.12899&volume=31&pages=1833-1842&publication_year=2021&author=Lu%2CY&author=Li%2CY&author=Zhou%2CH&author=Lin%2CJ&author=Zheng%2CZ&author=Xu%2CH&author=Lin%2CB&author=Lin%2CM&author=Liu%2CL)

25. Fantozzi, F., Lamberti, G., Leccese, F. & Salvadori, G. Monitoring CO 2 concentration to control the infection probability due to airborne transmission in naturally ventilated university classrooms. _Architect. Sci. Rev._ **65**, 306–318. [https://doi.org/10.1080/00038628.2022.2080637](https://doi.org/10.1080/00038628.2022.2080637) (2022).

    [Article](https://doi.org/10.1080%2F00038628.2022.2080637) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Monitoring%20CO%202%20concentration%20to%20control%20the%20infection%20probability%20due%20to%20airborne%20transmission%20in%20naturally%20ventilated%20university%20classrooms&journal=Architect.%20Sci.%20Rev.&doi=10.1080%2F00038628.2022.2080637&volume=65&pages=306-318&publication_year=2022&author=Fantozzi%2CF&author=Lamberti%2CG&author=Leccese%2CF&author=Salvadori%2CG)

26. Blocken, B. _et al._ Ventilation and air cleaning to limit aerosol particle concentrations in a gym during the COVID-19 pandemic. _Build. Environ._ **193**, 107659\. [https://doi.org/10.1016/j.buildenv.2021.107659](https://doi.org/10.1016/j.buildenv.2021.107659) (2021).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2021.107659) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DC%2BB3snisFSqug%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=33568882) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7860965) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Ventilation%20and%20air%20cleaning%20to%20limit%20aerosol%20particle%20concentrations%20in%20a%20gym%20during%20the%20COVID-19%20pandemic&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2021.107659&volume=193&publication_year=2021&author=Blocken%2CB&author=Druenen%2CT&author=Ricci%2CA&author=Kang%2CL&author=Hooff%2CT&author=Qin%2CP&author=Xia%2CL&author=Ruiz%2CCA&author=Arts%2CJH&author=Diepens%2CJFL)

27. Bourouiba, L. Turbulent gas clouds and respiratory pathogen emissions: Potential implications for reducing transmission of COVID-19. _JAMA_ [https://doi.org/10.1001/jama.2020.4756](https://doi.org/10.1001/jama.2020.4756) (2020).

    [Article](https://doi.org/10.1001%2Fjama.2020.4756) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32215590) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Turbulent%20gas%20clouds%20and%20respiratory%20pathogen%20emissions%3A%20Potential%20implications%20for%20reducing%20transmission%20of%20COVID-19&journal=JAMA&doi=10.1001%2Fjama.2020.4756&publication_year=2020&author=Bourouiba%2CL)

28. Busco, G., Yang, S. R., Seo, J. & Hassan, Y. A. Sneezing and asymptomatic virus transmission. _Phys. Fluids_ **32**, 073309\. [https://doi.org/10.1063/5.0019090](https://doi.org/10.1063/5.0019090) (2020).

    [Article](https://doi.org/10.1063%2F5.0019090) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020PhFl...32g3309B) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhsVSltrvO) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Sneezing%20and%20asymptomatic%20virus%20transmission&journal=Phys.%20Fluids&doi=10.1063%2F5.0019090&volume=32&publication_year=2020&author=Busco%2CG&author=Yang%2CSR&author=Seo%2CJ&author=Hassan%2CYA)

29. Gwaltney, J. M. _et al._ Nose blowing propels nasal fluid into the paranasal sinuses. _Clin. Infect. Dis._ **30**, 387–391. [https://doi.org/10.1086/313661](https://doi.org/10.1086/313661) (2000).

    [Article](https://doi.org/10.1086%2F313661) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10671347) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Nose%20blowing%20propels%20nasal%20fluid%20into%20the%20paranasal%20sinuses&journal=Clin.%20Infect.%20Dis.&doi=10.1086%2F313661&volume=30&pages=387-391&publication_year=2000&author=Gwaltney%2CJM&author=Hendley%2CJO&author=Phillips%2CCD&author=Bass%2CCR&author=Mygind%2CN&author=Winther%2CB)

30. Han, Z. Y., Weng, W. G. & Huang, Q. Y. Characterizations of particle size distribution of the droplets exhaled by sneeze. _J. R. Soc. Interface._ **10**, 20130560\. [https://doi.org/10.1098/rsif.2013.0560](https://doi.org/10.1098/rsif.2013.0560) (2013).

    [Article](https://doi.org/10.1098%2Frsif.2013.0560) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DC%2BC3sbnsVSqsQ%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=24026469) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC3785820) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Characterizations%20of%20particle%20size%20distribution%20of%20the%20droplets%20exhaled%20by%20sneeze&journal=J.%20R.%20Soc.%20Interface.&doi=10.1098%2Frsif.2013.0560&volume=10&publication_year=2013&author=Han%2CZY&author=Weng%2CWG&author=Huang%2CQY)

31. Fairchild, C. I. & Stampfer, J. F. Particle concentration in exhaled breath. _Am. Ind. Hyg. Assoc. Journal_ **48**, 948–949. [https://doi.org/10.1080/15298668791385868](https://doi.org/10.1080/15298668791385868) (1987).

    [Article](https://doi.org/10.1080%2F15298668791385868) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DyaL1cXis1CltQ%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=3425555) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Particle%20concentration%20in%20exhaled%20breath&journal=Am.%20Ind.%20Hyg.%20Assoc.%20Journal&doi=10.1080%2F15298668791385868&volume=48&pages=948-949&publication_year=1987&author=Fairchild%2CCI&author=Stampfer%2CJF)

32. Papineni, R. S. & Rosenthal, F. S. The size distribution of droplets in the exhaled breath of healthy human subjects. _J. Aerosol Med._ **10**, 105–116. [https://doi.org/10.1089/jam.1997.10.105](https://doi.org/10.1089/jam.1997.10.105) (1997).

    [Article](https://doi.org/10.1089%2Fjam.1997.10.105) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DyaK2sznsF2jtA%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10168531) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20size%20distribution%20of%20droplets%20in%20the%20exhaled%20breath%20of%20healthy%20human%20subjects&journal=J.%20Aerosol%20Med.&doi=10.1089%2Fjam.1997.10.105&volume=10&pages=105-116&publication_year=1997&author=Papineni%2CRS&author=Rosenthal%2CFS)

33. Mahajan, R. P., Singh, P., Murty, G. E. & Aitkenhead, A. R. Relationship between expired lung volume, peak flow rate and peak velocity time during a voluntary cough manoeuvre. _Br. J. Anaesth._ **72**, 298–301. [https://doi.org/10.1093/bja/72.3.298](https://doi.org/10.1093/bja/72.3.298) (1994).

    [Article](https://doi.org/10.1093%2Fbja%2F72.3.298) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DyaK2c7ns1eisA%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=8130048) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Relationship%20between%20expired%20lung%20volume%2C%20peak%20flow%20rate%20and%20peak%20velocity%20time%20during%20a%20voluntary%20cough%20manoeuvre&journal=Br.%20J.%20Anaesth.&doi=10.1093%2Fbja%2F72.3.298&volume=72&pages=298-301&publication_year=1994&author=Mahajan%2CRP&author=Singh%2CP&author=Murty%2CGE&author=Aitkenhead%2CAR)

34. Chao, C. Y. H. _et al._ Characterization of expiration air jets and droplet size distributions immediately at the mouth opening. _J. Aerosol Sci._ **40**, 122–133. [https://doi.org/10.1016/j.jaerosci.2008.10.003](https://doi.org/10.1016/j.jaerosci.2008.10.003) (2009).

    [Article](https://doi.org/10.1016%2Fj.jaerosci.2008.10.003) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2009JAerS..40..122C) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BD1MXhtFSns7Y%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32287373) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Characterization%20of%20expiration%20air%20jets%20and%20droplet%20size%20distributions%20immediately%20at%20the%20mouth%20opening&journal=J.%20Aerosol%20Sci.&doi=10.1016%2Fj.jaerosci.2008.10.003&volume=40&pages=122-133&publication_year=2009&author=Chao%2CCYH&author=Wan%2CMP&author=Morawska%2CL&author=Johnson%2CGR&author=Ristovski%2CZD&author=Hargreaves%2CM&author=Mengersen%2CK&author=Corbett%2CS&author=Li%2CY&author=Xie%2CX)

35. Gupta, J. K., Lin, C.-H. & Chen, Q. Characterizing exhaled airflow from breathing and talking. _Indoor Air_ **20**, 31–39. [https://doi.org/10.1111/j.1600-0668.2009.00623.x](https://doi.org/10.1111/j.1600-0668.2009.00623.x) (2010).

    [Article](https://doi.org/10.1111%2Fj.1600-0668.2009.00623.x) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=20028433) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Characterizing%20exhaled%20airflow%20from%20breathing%20and%20talking&journal=Indoor%20Air&doi=10.1111%2Fj.1600-0668.2009.00623.x&volume=20&pages=31-39&publication_year=2010&author=Gupta%2CJK&author=Lin%2CC-H&author=Chen%2CQ)

36. Anzai, H. _et al._ Coupled discrete phase model and Eulerian wall film model for numerical simulation of respiratory droplet generation during coughing. _Sci. Rep._ **12**, 14849\. [https://doi.org/10.1038/s41598-022-18788-3](https://doi.org/10.1038/s41598-022-18788-3) (2022).

    [Article](https://doi.org/10.1038%2Fs41598-022-18788-3) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2022NatSR..1214849A) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38XitlWmsrzF) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=36050319) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9434508) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Coupled%20discrete%20phase%20model%20and%20Eulerian%20wall%20film%20model%20for%20numerical%20simulation%20of%20respiratory%20droplet%20generation%20during%20coughing&journal=Sci.%20Rep.&doi=10.1038%2Fs41598-022-18788-3&volume=12&publication_year=2022&author=Anzai%2CH&author=Shindo%2CY&author=Kohata%2CY&author=Hasegawa%2CM&author=Takana%2CH&author=Matsunaga%2CT&author=Akaike%2CT&author=Ohta%2CM)

37. Stadnytskyi, V., Anfinrud, P. & Bax, A. Breathing, speaking, coughing or sneezing: What drives transmission of SARS-CoV-2?. _J. Intern. Med._ **290**, 1010–1027. [https://doi.org/10.1111/joim.13326](https://doi.org/10.1111/joim.13326) (2021).

    [Article](https://doi.org/10.1111%2Fjoim.13326) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXhslKhsbbF) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34105202) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8242678) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Breathing%2C%20speaking%2C%20coughing%20or%20sneezing%3A%20What%20drives%20transmission%20of%20SARS-CoV-2%3F&journal=J.%20Intern.%20Med.&doi=10.1111%2Fjoim.13326&volume=290&pages=1010-1027&publication_year=2021&author=Stadnytskyi%2CV&author=Anfinrud%2CP&author=Bax%2CA)

38. Wells, W. F. On air-borne infection\*: Study II. Droplets and droplet nuclei. _Am. J. Epidemiol._ **20**, 611–618. [https://doi.org/10.1093/oxfordjournals.aje.a118097](https://doi.org/10.1093/oxfordjournals.aje.a118097) (1934).

    [Article](https://doi.org/10.1093%2Foxfordjournals.aje.a118097) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=On%20air-borne%20infection%2A%3A%20Study%20II.%20Droplets%20and%20droplet%20nuclei&journal=Am.%20J.%20Epidemiol.&doi=10.1093%2Foxfordjournals.aje.a118097&volume=20&pages=611-618&publication_year=1934&author=Wells%2CWF)

39. Xie, X., Li, Y., Chwang, A. T. Y., Ho, P. L. & Seto, W. H. How far droplets can move in indoor environments? Revisiting the wells evaporation? Falling curve. _Indoor Air_ **17**, 211–225. [https://doi.org/10.1111/j.1600-0668.2007.00469.x](https://doi.org/10.1111/j.1600-0668.2007.00469.x) (2007).

    [Article](https://doi.org/10.1111%2Fj.1600-0668.2007.00469.x) [CAS](https://www.nature.com/articles/cas-redirect/1:STN:280:DC%2BD2szjtFOrtw%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=17542834) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=How%20far%20droplets%20can%20move%20in%20indoor%20environments%3F%20Revisiting%20the%20wells%20evaporation%3F%20Falling%20curve&journal=Indoor%20Air&doi=10.1111%2Fj.1600-0668.2007.00469.x&volume=17&pages=211-225&publication_year=2007&author=Xie%2CX&author=Li%2CY&author=Chwang%2CATY&author=Ho%2CPL&author=Seto%2CWH)

40. Motamedi, H., Shirzadi, M., Tominaga, Y. & Mirzaei, P. A. CFD modeling of airborne pathogen transmission of COVID-19 in confined spaces under different ventilation strategies. _Sustain. Cities Soc._ **76**, 103397\. [https://doi.org/10.1016/j.scs.2021.103397](https://doi.org/10.1016/j.scs.2021.103397) (2022).

    [Article](https://doi.org/10.1016%2Fj.scs.2021.103397) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34631393) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=CFD%20modeling%20of%20airborne%20pathogen%20transmission%20of%20COVID-19%20in%20confined%20spaces%20under%20different%20ventilation%20strategies&journal=Sustain.%20Cities%20Soc.&doi=10.1016%2Fj.scs.2021.103397&volume=76&publication_year=2022&author=Motamedi%2CH&author=Shirzadi%2CM&author=Tominaga%2CY&author=Mirzaei%2CPA)

41. Quiñones, J. J. _et al._ Prediction of respiratory droplets evolution for safer academic facilities planning amid COVID-19 and future pandemics: A numerical approach. _J. Build. Eng._ **54**, 104593\. [https://doi.org/10.1016/j.jobe.2022.104593](https://doi.org/10.1016/j.jobe.2022.104593) (2022).

    [Article](https://doi.org/10.1016%2Fj.jobe.2022.104593) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Prediction%20of%20respiratory%20droplets%20evolution%20for%20safer%20academic%20facilities%20planning%20amid%20COVID-19%20and%20future%20pandemics%3A%20A%20numerical%20approach&journal=J.%20Build.%20Eng.&doi=10.1016%2Fj.jobe.2022.104593&volume=54&publication_year=2022&author=Qui%C3%B1ones%2CJJ&author=Doosttalab%2CA&author=Sokolowski%2CS&author=Voyles%2CRM&author=Casta%C3%B1o%2CV&author=Zhang%2CLT&author=Castillo%2CL)

42. Pendar, M.-R. & Páscoa, J. C. Numerical modeling of the distribution of virus carrying saliva droplets during sneeze and cough. _Phys. Fluids_ **32**, 083305\. [https://doi.org/10.1063/5.0018432](https://doi.org/10.1063/5.0018432) (2020).

    [Article](https://doi.org/10.1063%2F5.0018432) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020PhFl...32h3305P) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhsF2qtr7E) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Numerical%20modeling%20of%20the%20distribution%20of%20virus%20carrying%20saliva%20droplets%20during%20sneeze%20and%20cough&journal=Phys.%20Fluids&doi=10.1063%2F5.0018432&volume=32&publication_year=2020&author=Pendar%2CM-R&author=P%C3%A1scoa%2CJC)

43. Chung, J. H., Kim, S., Sohn, D. K. & Ko, H. S. Ventilation efficiency according to tilt angle to reduce the transmission of infectious disease in classroom. _Indoor Built Environ._ **32**, 763–776. [https://doi.org/10.1177/1420326X221135829](https://doi.org/10.1177/1420326X221135829) (2023).

    [Article](https://doi.org/10.1177%2F1420326X221135829) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3sXhtVehsb7O) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Ventilation%20efficiency%20according%20to%20tilt%20angle%20to%20reduce%20the%20transmission%20of%20infectious%20disease%20in%20classroom&journal=Indoor%20Built%20Environ.&doi=10.1177%2F1420326X221135829&volume=32&pages=763-776&publication_year=2023&author=Chung%2CJH&author=Kim%2CS&author=Sohn%2CDK&author=Ko%2CHS)

44. Ovando-Chacon, G. E. _et al._ Computational study of thermal comfort and reduction of CO2 levels inside a classroom. _IJERPH_ **19**, 2956\. [https://doi.org/10.3390/ijerph19052956](https://doi.org/10.3390/ijerph19052956) (2022).

    [Article](https://doi.org/10.3390%2Fijerph19052956) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38Xnt1Sgurc%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=35270649) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8910020) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Computational%20study%20of%20thermal%20comfort%20and%20reduction%20of%20CO2%20levels%20inside%20a%20classroom&journal=IJERPH&doi=10.3390%2Fijerph19052956&volume=19&publication_year=2022&author=Ovando-Chacon%2CGE&author=Rodr%C3%ADguez-Le%C3%B3n%2CA&author=Ovando-Chacon%2CSL&author=Hern%C3%A1ndez-Ordo%C3%B1ez%2CM&author=D%C3%ADaz-Gonz%C3%A1lez%2CM&author=Pozos-Texon%2CFDJ)

45. Sarhan, A. R., Naser, P. & Naser, J. COVID-19 aerodynamic evaluation of social distancing in indoor environments, a numerical study. _J. Environ. Health Sci. Eng._ **19**, 1969–1978. [https://doi.org/10.1007/s40201-021-00748-0](https://doi.org/10.1007/s40201-021-00748-0) (2021).

    [Article](https://link.springer.com/doi/10.1007/s40201-021-00748-0) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXitlKmtL3J) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34721881) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8542656) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=COVID-19%20aerodynamic%20evaluation%20of%20social%20distancing%20in%20indoor%20environments%2C%20a%20numerical%20study&journal=J.%20Environ.%20Health%20Sci.%20Eng.&doi=10.1007%2Fs40201-021-00748-0&volume=19&pages=1969-1978&publication_year=2021&author=Sarhan%2CAR&author=Naser%2CP&author=Naser%2CJ)

46. D’Alicandro, A. C., Capozzoli, A. & Mauro, A. Thermofluid dynamics and droplets transport inside a large university classroom: Effects of occupancy rate and volumetric airflow. _J. Aerosol Sci._ **175**, 106285\. [https://doi.org/10.1016/j.jaerosci.2023.106285](https://doi.org/10.1016/j.jaerosci.2023.106285) (2024).

    [Article](https://doi.org/10.1016%2Fj.jaerosci.2023.106285) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3sXitFGmsbbL) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Thermofluid%20dynamics%20and%20droplets%20transport%20inside%20a%20large%20university%20classroom%3A%20Effects%20of%20occupancy%20rate%20and%20volumetric%20airflow&journal=J.%20Aerosol%20Sci.&doi=10.1016%2Fj.jaerosci.2023.106285&volume=175&publication_year=2024&author=D%E2%80%99Alicandro%2CAC&author=Capozzoli%2CA&author=Mauro%2CA)

47. Arpino, F. _et al._ CFD analysis of the air supply rate influence on the aerosol dispersion in a university lecture room. _Build. Environ._ **235**, 110257\. [https://doi.org/10.1016/j.buildenv.2023.110257](https://doi.org/10.1016/j.buildenv.2023.110257) (2023).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2023.110257) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=CFD%20analysis%20of%20the%20air%20supply%20rate%20influence%20on%20the%20aerosol%20dispersion%20in%20a%20university%20lecture%20room&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2023.110257&volume=235&publication_year=2023&author=Arpino%2CF&author=Cortellessa%2CG&author=D%E2%80%99Alicandro%2CAC&author=Grossi%2CG&author=Massarotti%2CN&author=Mauro%2CA)

48. Mboreha, C. A., Jianhong, S., Yan, W. & Zhi, S. Airflow and contaminant transport in innovative personalized ventilation systems for aircraft cabins: A numerical study. _Sci. Technol. Built Environ._ **28**, 557–574. [https://doi.org/10.1080/23744731.2022.2050632](https://doi.org/10.1080/23744731.2022.2050632) (2022).

    [Article](https://doi.org/10.1080%2F23744731.2022.2050632) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Airflow%20and%20contaminant%20transport%20in%20innovative%20personalized%20ventilation%20systems%20for%20aircraft%20cabins%3A%20A%20numerical%20study&journal=Sci.%20Technol.%20Built%20Environ.&doi=10.1080%2F23744731.2022.2050632&volume=28&pages=557-574&publication_year=2022&author=Mboreha%2CCA&author=Jianhong%2CS&author=Yan%2CW&author=Zhi%2CS)

49. Yang, Y. _et al._ Numerical investigation on the droplet dispersion inside a bus and the infection risk prediction. _Appl. Sci._ **12**, 5909\. [https://doi.org/10.3390/app12125909](https://doi.org/10.3390/app12125909) (2022).

    [Article](https://doi.org/10.3390%2Fapp12125909) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB38XhsFyisr%2FK) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Numerical%20investigation%20on%20the%20droplet%20dispersion%20inside%20a%20bus%20and%20the%20infection%20risk%20prediction&journal=Appl.%20Sci.&doi=10.3390%2Fapp12125909&volume=12&publication_year=2022&author=Yang%2CY&author=Wang%2CY&author=Su%2CC&author=Liu%2CX&author=Yuan%2CX&author=Chen%2CZ)

50. Shinohara, N. _et al._ Air exchange rates and advection-diffusion of CO2 and aerosols in a route bus for evaluation of infection risk. _Indoor Air_ [https://doi.org/10.1111/ina.13019](https://doi.org/10.1111/ina.13019) (2022).

    [Article](https://doi.org/10.1111%2Fina.13019) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=35347782) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9111735) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Air%20exchange%20rates%20and%20advection-diffusion%20of%20CO2%20and%20aerosols%20in%20a%20route%20bus%20for%20evaluation%20of%20infection%20risk&journal=Indoor%20Air&doi=10.1111%2Fina.13019&publication_year=2022&author=Shinohara%2CN&author=Tatsu%2CK&author=Kagi%2CN&author=Kim%2CH&author=Sakaguchi%2CJ&author=Ogura%2CI&author=Murashima%2CY&author=Sakurai%2CH&author=Naito%2CW)

51. Le, T.-L., Nguyen, T. T. & Kieu, T. T. A CFD study on the design optimization of airborne infection isolation room. _Math. Probl. Eng._ **2022**, 1–10. [https://doi.org/10.1155/2022/5419671](https://doi.org/10.1155/2022/5419671) (2022).

    [Article](https://doi.org/10.1155%2F2022%2F5419671) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3sXnsFeqtbw%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=A%20CFD%20study%20on%20the%20design%20optimization%20of%20airborne%20infection%20isolation%20room&journal=Math.%20Probl.%20Eng.&doi=10.1155%2F2022%2F5419671&volume=2022&pages=1-10&publication_year=2022&author=Le%2CT-L&author=Nguyen%2CTT&author=Kieu%2CTT)

52. Liu, Z. _et al._ A novel approach for predicting the concentration of exhaled aerosols exposure among healthcare workers in the operating room. _Build. Environ._ **245**, 110867\. [https://doi.org/10.1016/j.buildenv.2023.110867](https://doi.org/10.1016/j.buildenv.2023.110867) (2023).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2023.110867) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=A%20novel%20approach%20for%20predicting%20the%20concentration%20of%20exhaled%20aerosols%20exposure%20among%20healthcare%20workers%20in%20the%20operating%20room&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2023.110867&volume=245&publication_year=2023&author=Liu%2CZ&author=Huang%2CZ&author=Chu%2CJ&author=Li%2CH&author=He%2CJ&author=Lin%2CC&author=Jiang%2CC&author=Yao%2CG&author=Fan%2CS)

53. Du, C. & Chen, Q. Virus transport and infection evaluation in a passenger elevator with a COVID-19 patient. _Indoor Air_ [https://doi.org/10.1111/ina.13125](https://doi.org/10.1111/ina.13125) (2022).

    [Article](https://doi.org/10.1111%2Fina.13125) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=36305070) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9874880) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Virus%20transport%20and%20infection%20evaluation%20in%20a%20passenger%20elevator%20with%20a%20COVID-19%20patient&journal=Indoor%20Air&doi=10.1111%2Fina.13125&publication_year=2022&author=Du%2CC&author=Chen%2CQ)

54. Liu, S. _et al._ Evaluation of airborne particle exposure for riding elevators. _Build. Environ._ **207**, 108543\. [https://doi.org/10.1016/j.buildenv.2021.108543](https://doi.org/10.1016/j.buildenv.2021.108543) (2022).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2021.108543) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34776597) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Evaluation%20of%20airborne%20particle%20exposure%20for%20riding%20elevators&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2021.108543&volume=207&publication_year=2022&author=Liu%2CS&author=Zhao%2CX&author=Nichols%2CSR&author=Bonilha%2CMW&author=Derwinski%2CT&author=Auxier%2CJT&author=Chen%2CQ)

55. Dbouk, T. & Drikakis, D. On airborne virus transmission in elevators and confined spaces. _Phys. Fluids_ **33**, 011905\. [https://doi.org/10.1063/5.0038180](https://doi.org/10.1063/5.0038180) (2021).

    [Article](https://doi.org/10.1063%2F5.0038180) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2021PhFl...33a1905D) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXitlGhs7c%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=On%20airborne%20virus%20transmission%20in%20elevators%20and%20confined%20spaces&journal=Phys.%20Fluids&doi=10.1063%2F5.0038180&volume=33&publication_year=2021&author=Dbouk%2CT&author=Drikakis%2CD)

56. Tipnis, P. M., Chaware, P. & Vaidya, V. G. Guidelines for elevator design to mitigate the risk of spread of airborne diseases. _Microb. Risk Anal._ **26**, 100289\. [https://doi.org/10.1016/j.mran.2023.100289](https://doi.org/10.1016/j.mran.2023.100289) (2024).

    [Article](https://doi.org/10.1016%2Fj.mran.2023.100289) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Guidelines%20for%20elevator%20design%20to%20mitigate%20the%20risk%20of%20spread%20of%20airborne%20diseases&journal=Microb.%20Risk%20Anal.&doi=10.1016%2Fj.mran.2023.100289&volume=26&publication_year=2024&author=Tipnis%2CPM&author=Chaware%2CP&author=Vaidya%2CVG)

57. Chillón, S. A., Ugarte-Anero, A., Aramendia, I., Fernandez-Gamiz, U. & Zulueta, E. Numerical modeling of the spread of cough saliva droplets in a calm confined space. _Mathematics_ **9**, 574\. [https://doi.org/10.3390/math9050574](https://doi.org/10.3390/math9050574) (2021).

    [Article](https://doi.org/10.3390%2Fmath9050574) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Numerical%20modeling%20of%20the%20spread%20of%20cough%20saliva%20droplets%20in%20a%20calm%20confined%20space&journal=Mathematics&doi=10.3390%2Fmath9050574&volume=9&publication_year=2021&author=Chill%C3%B3n%2CSA&author=Ugarte-Anero%2CA&author=Aramendia%2CI&author=Fernandez-Gamiz%2CU&author=Zulueta%2CE)

58. Chillón, S. A., Fernandez-Gamiz, U., Zulueta, E., Ugarte-Anero, A. & Urbina-Garcia, O. Numerical modeling of a sneeze, a cough and a continuum speech inside a hospital lift. _Heliyon_ **9**, e13370. [https://doi.org/10.1016/j.heliyon.2023.e13370](https://doi.org/10.1016/j.heliyon.2023.e13370) (2023).

    [Article](https://doi.org/10.1016%2Fj.heliyon.2023.e13370) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=36744064) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9889118) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Numerical%20modeling%20of%20a%20sneeze%2C%20a%20cough%20and%20a%20continuum%20speech%20inside%20a%20hospital%20lift&journal=Heliyon&doi=10.1016%2Fj.heliyon.2023.e13370&volume=9&publication_year=2023&author=Chill%C3%B3n%2CSA&author=Fernandez-Gamiz%2CU&author=Zulueta%2CE&author=Ugarte-Anero%2CA&author=Urbina-Garcia%2CO)

59. Dbouk, T. & Drikakis, D. On coughing and airborne droplet transmission to humans. _Phys. Fluids_ **32**, 053310\. [https://doi.org/10.1063/5.0011960](https://doi.org/10.1063/5.0011960) (2020).

    [Article](https://doi.org/10.1063%2F5.0011960) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020PhFl...32e3310D) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhtVSisbnM) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=On%20coughing%20and%20airborne%20droplet%20transmission%20to%20humans&journal=Phys.%20Fluids&doi=10.1063%2F5.0011960&volume=32&publication_year=2020&author=Dbouk%2CT&author=Drikakis%2CD)

60. Mhetre, M. R. & Abhyankar, H. K. Human exhaled air energy harvesting with specific reference to PVDF film. _Eng. Sci. Technol. Int. J._ **20**, 332–339. [https://doi.org/10.1016/j.jestch.2016.06.012](https://doi.org/10.1016/j.jestch.2016.06.012) (2017).

    [Article](https://doi.org/10.1016%2Fj.jestch.2016.06.012) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Human%20exhaled%20air%20energy%20harvesting%20with%20specific%20reference%20to%20PVDF%20film&journal=Eng.%20Sci.%20Technol.%20Int.%20J.&doi=10.1016%2Fj.jestch.2016.06.012&volume=20&pages=332-339&publication_year=2017&author=Mhetre%2CMR&author=Abhyankar%2CHK)

61. Hibbard, T. & Killard, A. J. Breath ammonia analysis: Clinical application and measurement. _Crit. Rev. Anal. Chem._ **41**, 21–35. [https://doi.org/10.1080/10408347.2011.521729](https://doi.org/10.1080/10408347.2011.521729) (2011).

    [Article](https://doi.org/10.1080%2F10408347.2011.521729) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BC3MXhvVCqtLo%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Breath%20ammonia%20analysis%3A%20Clinical%20application%20and%20measurement&journal=Crit.%20Rev.%20Anal.%20Chem.&doi=10.1080%2F10408347.2011.521729&volume=41&pages=21-35&publication_year=2011&author=Hibbard%2CT&author=Killard%2CAJ)

62. Pham, D. A., Lim, Y.-I., Jee, H., Ahn, E. & Jung, Y. Porous media Eulerian computational fluid dynamics (CFD) model of amine absorber with structured-packing for CO2 removal. _Chem. Eng. Sci._ **132**, 259–270. [https://doi.org/10.1016/j.ces.2015.04.009](https://doi.org/10.1016/j.ces.2015.04.009) (2015).

    [Article](https://doi.org/10.1016%2Fj.ces.2015.04.009) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BC2MXntFKiur4%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Porous%20media%20Eulerian%20computational%20fluid%20dynamics%20%28CFD%29%20model%20of%20amine%20absorber%20with%20structured-packing%20for%20CO2%20removal&journal=Chem.%20Eng.%20Sci.&doi=10.1016%2Fj.ces.2015.04.009&volume=132&pages=259-270&publication_year=2015&author=Pham%2CDA&author=Lim%2CY-I&author=Jee%2CH&author=Ahn%2CE&author=Jung%2CY)

63. Sadeghizadeh, A., Rahimi, R. & Farhad Dad, F. Computational fluid dynamics modeling of carbon dioxide capture from air using biocatalyst in an airlift reactor. _Bioresour. Technol._ **253**, 154–164. [https://doi.org/10.1016/j.biortech.2018.01.025](https://doi.org/10.1016/j.biortech.2018.01.025) (2018).

    [Article](https://doi.org/10.1016%2Fj.biortech.2018.01.025) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BC1cXosVKhtA%3D%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=29353746) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Computational%20fluid%20dynamics%20modeling%20of%20carbon%20dioxide%20capture%20from%20air%20using%20biocatalyst%20in%20an%20airlift%20reactor&journal=Bioresour.%20Technol.&doi=10.1016%2Fj.biortech.2018.01.025&volume=253&pages=154-164&publication_year=2018&author=Sadeghizadeh%2CA&author=Rahimi%2CR&author=Farhad%20Dad%2CF)

64. Roache, P. J. Perspective: A method for uniform reporting of grid refinement studies. _J. Fluids Eng._ **116**, 405–413. [https://doi.org/10.1115/1.2910291](https://doi.org/10.1115/1.2910291) (1994).

    [Article](https://doi.org/10.1115%2F1.2910291) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Perspective%3A%20A%20method%20for%20uniform%20reporting%20of%20grid%20refinement%20studies&journal=J.%20Fluids%20Eng.&doi=10.1115%2F1.2910291&volume=116&pages=405-413&publication_year=1994&author=Roache%2CPJ)

65. Alfonsi, G. Reynolds-averaged Navier–Stokes equations for turbulence modeling. _Appl. Mech. Rev._ **62**, 040802\. [https://doi.org/10.1115/1.3124648](https://doi.org/10.1115/1.3124648) (2009).

    [Article](https://doi.org/10.1115%2F1.3124648) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2009ApMRv..62d0802A) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Reynolds-averaged%20Navier%E2%80%93Stokes%20equations%20for%20turbulence%20modeling&journal=Appl.%20Mech.%20Rev.&doi=10.1115%2F1.3124648&volume=62&publication_year=2009&author=Alfonsi%2CG)

66. Zhu, S., Kato, S. & Yang, J.-H. Study on transport characteristics of saliva droplets produced by coughing in a calm indoor environment. _Build. Environ._ **41**, 1691–1702. [https://doi.org/10.1016/j.buildenv.2005.06.024](https://doi.org/10.1016/j.buildenv.2005.06.024) (2006).

    [Article](https://doi.org/10.1016%2Fj.buildenv.2005.06.024) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Study%20on%20transport%20characteristics%20of%20saliva%20droplets%20produced%20by%20coughing%20in%20a%20calm%20indoor%20environment&journal=Build.%20Environ.&doi=10.1016%2Fj.buildenv.2005.06.024&volume=41&pages=1691-1702&publication_year=2006&author=Zhu%2CS&author=Kato%2CS&author=Yang%2CJ-H)

67. Wang, B., Wu, H. & Wan, X.-F. Transport and fate of human expiratory droplets—a modeling approach. _Phys. Fluids_ **32**, 083307\. [https://doi.org/10.1063/5.0021280](https://doi.org/10.1063/5.0021280) (2020).

    [Article](https://doi.org/10.1063%2F5.0021280) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020PhFl...32h3307W) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhs1ert7zK) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Transport%20and%20fate%20of%20human%20expiratory%20droplets%E2%80%94a%20modeling%20approach&journal=Phys.%20Fluids&doi=10.1063%2F5.0021280&volume=32&publication_year=2020&author=Wang%2CB&author=Wu%2CH&author=Wan%2CX-F)

68. Wang, Z., Galea, E. R., Grandison, A., Ewer, J. & Jia, F. A coupled computational fluid dynamics and Wells-Riley model to predict COVID-19 infection probability for passengers on long-distance trains. _Saf. Sci._ **147**, 105572\. [https://doi.org/10.1016/j.ssci.2021.105572](https://doi.org/10.1016/j.ssci.2021.105572) (2022).

    [Article](https://doi.org/10.1016%2Fj.ssci.2021.105572) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34803226) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=A%20coupled%20computational%20fluid%20dynamics%20and%20Wells-Riley%20model%20to%20predict%20COVID-19%20infection%20probability%20for%20passengers%20on%20long-distance%20trains&journal=Saf.%20Sci.&doi=10.1016%2Fj.ssci.2021.105572&volume=147&publication_year=2022&author=Wang%2CZ&author=Galea%2CER&author=Grandison%2CA&author=Ewer%2CJ&author=Jia%2CF)

69. Foster, A. & Kinzel, M. Estimating COVID-19 exposure in a classroom setting: A comparison between mathematical and numerical models. _Phys. Fluids_ **33**, 021904\. [https://doi.org/10.1063/5.0040755](https://doi.org/10.1063/5.0040755) (2021).

    [Article](https://doi.org/10.1063%2F5.0040755) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2021PhFl...33b1904F) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXlsFSju7w%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Estimating%20COVID-19%20exposure%20in%20a%20classroom%20setting%3A%20A%20comparison%20between%20mathematical%20and%20numerical%20models&journal=Phys.%20Fluids&doi=10.1063%2F5.0040755&volume=33&publication_year=2021&author=Foster%2CA&author=Kinzel%2CM)

70. Carpenter, G. H. The secretion, components, and properties of saliva. _Annu. Rev. Food Sci. Technol._ **4**, 267–276. [https://doi.org/10.1146/annurev-food-030212-182700](https://doi.org/10.1146/annurev-food-030212-182700) (2013).

    [Article](https://doi.org/10.1146%2Fannurev-food-030212-182700) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BC3sXntFyns7o%3D) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=23464573) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20secretion%2C%20components%2C%20and%20properties%20of%20saliva&journal=Annu.%20Rev.%20Food%20Sci.%20Technol.&doi=10.1146%2Fannurev-food-030212-182700&volume=4&pages=267-276&publication_year=2013&author=Carpenter%2CGH)

71. Nicas, M., Nazaroff, W. W. & Hubbard, A. Toward understanding the risk of secondary airborne infection: Emission of respirable pathogens. _J. Occup. Environ. Hyg._ **2**, 143–154. [https://doi.org/10.1080/15459620590918466](https://doi.org/10.1080/15459620590918466) (2005).

    [Article](https://doi.org/10.1080%2F15459620590918466) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=15764538) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Toward%20understanding%20the%20risk%20of%20secondary%20airborne%20infection%3A%20Emission%20of%20respirable%20pathogens&journal=J.%20Occup.%20Environ.%20Hyg.&doi=10.1080%2F15459620590918466&volume=2&pages=143-154&publication_year=2005&author=Nicas%2CM&author=Nazaroff%2CWW&author=Hubbard%2CA)

72. Ranz, W. & Marshall, W. Evaporation from drops. _Chem. Eng. Prog._ **48**, 141–146 (1952).

    [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DyaG38Xit1emtA%3D%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Evaporation%20from%20Drops&journal=Chem.%20Eng.%20Prog.&volume=48&pages=141-146&publication_year=1952&author=Ranz%2CW&author=Marshall%2CW)


[Download references](https://citation-needed.springer.com/v2/references/10.1038/s41598-024-57425-z?format=refman&flavour=references)

## Acknowledgements

The authors are grateful for the support provided by SGIker of UPV/EHU.

## Funding

The authors appreciate the support given to the government of the Basque Country through the research programs Grants N. ELKARTEK 20/71 and ELKARTEK 20/78. Additionally, we would like to thank the Research Group: IT1514-22.

## Author information

### Authors and Affiliations

1. Energy Engineering Department, School of Engineering of Vitoria-Gasteiz, University of the Basque Country, UPV/EHU, Nieves Cano 12, 01006, Vitoria-Gasteiz, Araba, Spain

Sergio A. Chillón, Unai Fernandez-Gamiz & Ainara Ugarte-Anero

2. Automatic and Simulation Department, University of the Basque Country, UPV/EHU, Nieves Cano 12, 01006, Vitoria-Gasteiz, Araba, Spain

Ekaitz Zulueta

3. Energy Engineering Department, School of Engineering, University of the Basque Country (UPV/EHU), Plaza Ingeniero Torres Quevedo, Building 1, 48013, Bilbao, Spain

Jesus Maria Blanco


Authors

1. Sergio A. Chillón


[View author publications](https://www.nature.com/search?author=Sergio%20A.%20Chill%C3%B3n)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Sergio%20A.%20Chill%C3%B3n) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Sergio%20A.%20Chill%C3%B3n%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

2. Unai Fernandez-Gamiz


[View author publications](https://www.nature.com/search?author=Unai%20Fernandez-Gamiz)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Unai%20Fernandez-Gamiz) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Unai%20Fernandez-Gamiz%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

3. Ekaitz Zulueta


[View author publications](https://www.nature.com/search?author=Ekaitz%20Zulueta)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Ekaitz%20Zulueta) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Ekaitz%20Zulueta%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

4. Ainara Ugarte-Anero


[View author publications](https://www.nature.com/search?author=Ainara%20Ugarte-Anero)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Ainara%20Ugarte-Anero) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Ainara%20Ugarte-Anero%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

5. Jesus Maria Blanco


[View author publications](https://www.nature.com/search?author=Jesus%20Maria%20Blanco)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Jesus%20Maria%20Blanco) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Jesus%20Maria%20Blanco%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)


### Contributions

(1) Conceived and designed the experiments; S.A.C., U.F.-G. and E.Z. (2) Performed the experiments; S.A.C., A.U.-A. and J.M.-B. (3) Analysed and interpreted the data; S.A.C., E.Z., U.F.-G. and A.U.-A. (4) Contributed reagents, materials, analysis tools or data; S.A.C., A.U.-A., J.M.-B., U.F.-G. and E.Z. (5) Wrote the paper; S.A.C., J.M.-B. and A.U.-A.

### Corresponding author

Correspondence to
[Unai Fernandez-Gamiz](mailto:unai.fernandez@ehu.eus).

## Ethics declarations

### Competing interests

The authors declare no competing interests.

## Additional information

### Publisher's note

Springer Nature remains neutral with regard to jurisdictional claims in published maps and institutional affiliations.

## Supplementary Information

### [Supplementary Information. (download DOCX )](https://static-content.springer.com/esm/art%3A10.1038%2Fs41598-024-57425-z/MediaObjects/41598_2024_57425_MOESM1_ESM.docx)

## Rights and permissions

**Open Access** This article is licensed under a Creative Commons Attribution 4.0 International License, which permits use, sharing, adaptation, distribution and reproduction in any medium or format, as long as you give appropriate credit to the original author(s) and the source, provide a link to the Creative Commons licence, and indicate if changes were made. The images or other third party material in this article are included in the article's Creative Commons licence, unless indicated otherwise in a credit line to the material. If material is not included in the article's Creative Commons licence and your intended use is not permitted by statutory regulation or exceeds the permitted use, you will need to obtain permission directly from the copyright holder. To view a copy of this licence, visit [http://creativecommons.org/licenses/by/4.0/](http://creativecommons.org/licenses/by/4.0/).

[Reprints and permissions](https://s100.copyright.com/AppDispatchServlet?title=Numerical%20performance%20of%20CO2%20accumulation%20and%20droplet%20dispersion%20from%20a%20cough%20inside%20a%20hospital%20lift%20under%20different%20ventilation%20strategies&author=Sergio%20A.%20Chill%C3%B3n%20et%20al&contentID=10.1038%2Fs41598-024-57425-z&copyright=The%20Author%28s%29&publication=2045-2322&publicationDate=2024-03-21&publisherName=SpringerNature&orderBeanReset=true&oa=CC%20BY)

## About this article

[![Check for updates. Verify currency and authenticity via CrossMark](<Base64-Image-Removed>)](https://crossmark.crossref.org/dialog/?doi=10.1038/s41598-024-57425-z)

### Cite this article

Chillón, S.A., Fernandez-Gamiz, U., Zulueta, E. _et al._ Numerical performance of CO2 accumulation and droplet dispersion from a cough inside a hospital lift under different ventilation strategies.
_Sci Rep_ **14**, 6843 (2024). https://doi.org/10.1038/s41598-024-57425-z

[Download citation](https://citation-needed.springer.com/v2/references/10.1038/s41598-024-57425-z?format=refman&flavour=citation)

- Received: 09 November 2023

- Accepted: 18 March 2024

- Published: 21 March 2024

- Version of record: 21 March 2024

- DOI: https://doi.org/10.1038/s41598-024-57425-z


### Share this article

Anyone you share the following link with will be able to read this content:

Get shareable link

Sorry, a shareable link is not currently available for this article.

Copy shareable link to clipboard

Provided by the Springer Nature SharedIt content-sharing initiative


### Keywords

- [CFD](https://www.nature.com/search?query=CFD&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)
- [COVID-19](https://www.nature.com/search?query=COVID-19&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)
- [Interior ventilation](https://www.nature.com/search?query=Interior%20ventilation&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)
- [Droplet contagious](https://www.nature.com/search?query=Droplet%20contagious&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)
- [Airborne transmission](https://www.nature.com/search?query=Airborne%20transmission&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)
- [Cough](https://www.nature.com/search?query=Cough&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)
- [Hospital lift](https://www.nature.com/search?query=Hospital%20lift&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)
- [CO2 transport](https://www.nature.com/search?query=CO%20transport&facet-discipline=%22Science%2C%20Humanities%20and%20Social%20Sciences%2C%20multidisciplinary%22)

### Subjects

- [Environmental social sciences](https://www.nature.com/subjects/environmental-social-sciences)
- [Mechanical engineering](https://www.nature.com/subjects/mechanical-engineering)

Close bannerClose

![Nature Briefing Anthropocene](https://www.nature.com/static/images/logos/nature-briefing-anthropocene-logo-55353f564d.svg)

Sign up for the _Nature Briefing: Anthropocene_ newsletter — what matters in anthropocene research, free to your inbox weekly.

Email address

Sign up

I agree my information will be processed in accordance with the _Nature_ and Springer Nature Limited [Privacy Policy](https://www.nature.com/info/privacy).

Close bannerClose

Get the most important science stories of the day, free in your inbox. [Sign up for Nature Briefing: Anthropocene](https://www.nature.com/briefing/anthropocene/?brieferEntryPoint=AnthropoceneBriefingBanner)