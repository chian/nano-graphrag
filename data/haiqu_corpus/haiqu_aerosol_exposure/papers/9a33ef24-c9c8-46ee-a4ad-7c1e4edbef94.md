Loading \[MathJax\]/jax/output/HTML-CSS/config.js

[Skip to main content](https://www.nature.com/articles/s41598-022-19898-8#content)

Thank you for visiting nature.com. You are using a browser version with limited support for CSS. To obtain
the best experience, we recommend you use a more up to date browser (or turn off compatibility mode in
Internet Explorer). In the meantime, to ensure continued support, we are displaying the site without styles
and JavaScript.

Investigating the effects of absolute humidity and movement on COVID-19 seasonality in the United States


[Download PDF](https://www.nature.com/articles/s41598-022-19898-8.pdf)

[Download PDF](https://www.nature.com/articles/s41598-022-19898-8.pdf)

## Abstract

Mounting evidence suggests the primary mode of SARS-CoV-2 transmission is aerosolized transmission from close contact with infected individuals. While transmission is a direct result of human encounters, falling humidity may enhance aerosolized transmission risks similar to other respiratory viruses (e.g., influenza). Using Google COVID-19 Community Mobility Reports, we assessed the relative effects of absolute humidity and changes in individual movement patterns on daily cases while accounting for regional differences in climatological regimes. Our results indicate that increasing humidity was associated with declining cases in the spring and summer of 2020, while decreasing humidity and increase in residential mobility during winter months likely caused increases in COVID-19 cases. The effects of humidity were generally greater in regions with lower humidity levels. Given the possibility that COVID-19 will be endemic, understanding the behavioral and environmental drivers of COVID-19 seasonality in the United States will be paramount as policymakers, healthcare systems, and researchers forecast and plan accordingly.

### Similar content being viewed by others

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs43588-021-00136-6/MediaObjects/43588_2021_136_Fig1_HTML.png)

### [Climatic signatures in the different COVID-19 pandemic waves across both hemispheres](https://www.nature.com/articles/s43588-021-00136-6?fromPaywallRec=false)

Article21 October 2021

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41598-021-91798-9/MediaObjects/41598_2021_91798_Fig1_HTML.png)

### [Cold and dry winter conditions are associated with greater SARS-CoV-2 transmission at regional level in western countries during the first epidemic wave](https://www.nature.com/articles/s41598-021-91798-9?fromPaywallRec=false)

ArticleOpen access17 June 2021

![](https://media.springernature.com/w215h120/springer-static/image/art%3A10.1038%2Fs41370-022-00472-3/MediaObjects/41370_2022_472_Fig1_HTML.png)

### [Associative evidence for the potential of humidification as a non-pharmaceutical intervention for influenza and SARS-CoV-2 transmission](https://www.nature.com/articles/s41370-022-00472-3?fromPaywallRec=false)

Article14 September 2022

## Introduction

As of October 14, 2021, the coronavirus disease 2019 (COVID-19) pandemic has claimed over 720,000 lives in the United States alone, with more than 44.7 million confirmed cases[1](https://www.nature.com/articles/s41598-022-19898-8#ref-CR1 "Dong, E., Du, H. & Gardner, L. An interactive web-based dashboard to track COVID-19 in real time. Lancet Infect. Dis. 20, 533–534 (2020)."). Current evidence suggests that the primary mode of transmission of the severe acute respiratory syndrome coronavirus 2 (SARS-CoV-2) is close contact with infected individuals[2](https://www.nature.com/articles/s41598-022-19898-8#ref-CR2 "Liu, J. et al. Community transmission of severe acute respiratory syndrome coronavirus 2, Shenzhen, China, 2020. Emerg. Infect. Dis. 26, 1320–1323 (2020)."), [3](https://www.nature.com/articles/s41598-022-19898-8#ref-CR3 "Chan, J.F.-W. et al. A familial cluster of pneumonia associated with the 2019 novel coronavirus indicating person-to-person transmission: A study of a family cluster. The Lancet 395, 514–523 (2020)."). Aerosols[4](https://www.nature.com/articles/s41598-022-19898-8#ref-CR4 "CDC. Coronavirus Disease 2019 (COVID-19). Centers for Disease Control and Prevention.                    https://www.cdc.gov/coronavirus/2019-ncov/more/scientific-brief-sars-cov-2.html                                     (2020)."), [5](https://www.nature.com/articles/s41598-022-19898-8#ref-CR5 "Tang, S. et al. Aerosol transmission of SARS-CoV-2? evidence, prevention and control. Environ. Int. 144, 106039 (2020)."), which are particulates less than 5 µm in diameter[6](https://www.nature.com/articles/s41598-022-19898-8#ref-CR6 "Ma, J. et al. Coronavirus disease 2019 patients in earlier stages exhaled millions of severe acute respiratory syndrome coronavirus 2 per hour. Clin. Infect. Dis.                    https://doi.org/10.1093/cid/ciaa1283                                     (2021)."), [7](https://www.nature.com/articles/s41598-022-19898-8#ref-CR7 "de Man, P. et al. Outbreak of coronavirus disease 2019 (COVID-19) in a nursing home associated with aerosol transmission as a result of inadequate ventilation. Clin. Infect. Dis.                    https://doi.org/10.1093/cid/ciaa1270                                     (2021)."), likely play a significant role in transmission[8](https://www.nature.com/articles/s41598-022-19898-8#ref-CR8 "Rahman, H. S. et al. The transmission modes and sources of COVID-19: A systematic review. Int. J. Surg. Open 26, 125–136 (2020)."). After the initial rise of cases in the early winter of 2020, cases remained severe through the spring before dropping in the summer. Given the shelter-in-place order in most states and the rise in humidity, cases generally decreased in May and stayed in lower ranges through the summer until the fall months. In most areas of the northern hemisphere, as fall turns to winter, the weather becomes colder and drier. Lower absolute humidity has been shown to be associated with increased transmission rates of other respiratory viruses (e.g., influenza)[9](https://www.nature.com/articles/s41598-022-19898-8#ref-CR9 "Shaman, J. & Kohn, M. Absolute humidity modulates influenza survival, transmission, and seasonality. Proc. Natl. Acad. Sci. 106, 3243–3248 (2009)."), posing significant concerns regarding potential increases in the number of COVID-19 cases in the fall and winter. The surge in cases through the end of 2020 further supports the seasonal effects of COVID-19.

While several studies have suggested a relationship between climatic factors (e.g., temperature and/or humidity) and COVID-19[10](https://www.nature.com/articles/s41598-022-19898-8#ref-CR10 "Wu, Y. et al. Effects of temperature and humidity on the daily new cases and new deaths of COVID-19 in 166 countries. Sci. Total Environ. 729, 139051 (2020)."), [11](https://www.nature.com/articles/s41598-022-19898-8#ref-CR11 "Kato, M., Sakihama, T., Kinjo, Y., Itokazu, D. & Tokuda, Y. Effect of Climate on COVID-19 Incidence: A Cross-Sectional Study in Japan.                    https://papers.ssrn.com/abstract=3612114                                    .                    https://doi.org/10.2139/ssrn.3612114                                     (2020)."), [12](https://www.nature.com/articles/s41598-022-19898-8#ref-CR12 "Christophi, C. A. et al. Ambient Temperature and Subsequent COVID-19 Mortality in the OECD Countries and Individual United States.                    https://papers.ssrn.com/abstract=3612112                                    .                    https://doi.org/10.2139/ssrn.3612112                                     (2020)."), [13](https://www.nature.com/articles/s41598-022-19898-8#ref-CR13 "Meyer, A., Sadler, R., Faverjon, C., Cameron, A. R. & Bannister-Tyrrell, M. Evidence that higher temperatures are associated with a marginally lower incidence of COVID-19 cases. Front. Public Health                    https://doi.org/10.3389/fpubh.2020.00367                                     (2020)."), [14](https://www.nature.com/articles/s41598-022-19898-8#ref-CR14 "Steiger, E., Mussgnug, T. & Kroll, L. E. Causal analysis of COVID-19 observational data in German districts reveals effects of mobility, awareness, and temperature. medRxiv                    https://doi.org/10.1101/2020.07.15.20154476                                     (2020)."), [15](https://www.nature.com/articles/s41598-022-19898-8#ref-CR15 "Kifer, D. et al. Effects of environmental factors on severity and mortality of COVID-19. medRxiv                    https://doi.org/10.1101/2020.07.11.20147157                                     (2020)."), [16](https://www.nature.com/articles/s41598-022-19898-8#ref-CR16 "Sehra, S. T., Salciccioli, J. D., Wiebe, D. J., Fundin, S. & Baker, J. F. Maximum daily temperature, precipitation, ultraviolet light, and rates of transmission of severe acute respiratory syndrome coronavirus 2 in the United States. Clin. Infect. Dis.                    https://doi.org/10.1093/cid/ciaa681                                     (2020)."), [17](https://www.nature.com/articles/s41598-022-19898-8#ref-CR17 "Mecenas, P., da Rosa Moreira Bastos, R. T., Vallinoto, A. C. R. & Normando, D. Effects of temperature and humidity on the spread of COVID-19: A systematic review. PLOS ONE 15, e0238339 (2020)."), [18](https://www.nature.com/articles/s41598-022-19898-8#ref-CR18 "Aragão, D. P. et al. Multivariate data driven prediction of COVID-19 dynamics: Towards new results with temperature, humidity and air quality data. Environ. Res. 204, 112348 (2022)."), the exact environmental and biological mechanism behind airborne and droplet transmission and viral survival of SARS-CoV-2[19](https://www.nature.com/articles/s41598-022-19898-8#ref-CR19 "Yuan, S., Jiang, S.-C. & Li, Z.-L. Do humidity and temperature impact the spread of the novel coronavirus?. Front. Public Health                    https://doi.org/10.3389/fpubh.2020.00240                                     (2020).") is not yet clear. In influenza, lower atmospheric moisture has been shown to increase the production of aerosol nuclei and viral survival time[9](https://www.nature.com/articles/s41598-022-19898-8#ref-CR9 "Shaman, J. & Kohn, M. Absolute humidity modulates influenza survival, transmission, and seasonality. Proc. Natl. Acad. Sci. 106, 3243–3248 (2009)."), which translates to higher risks of airborne and droplet transmission. Other climatic factors that may impact transmission include temperature and air quality[20](https://www.nature.com/articles/s41598-022-19898-8#ref-CR20 "Lolli, S., Chen, Y.-C., Wang, S.-H. & Vivone, G. Impact of meteorological conditions and air pollution on COVID-19 pandemic transmission in Italy. Sci. Rep. 10, 16213 (2020)."), [21](https://www.nature.com/articles/s41598-022-19898-8#ref-CR21 "Sajadi, M. M. et al. Temperature, humidity, and latitude analysis to estimate potential spread and seasonality of coronavirus disease 2019 (COVID-19). JAMA Netw. Open 3, e2011834 (2020)."); nevertheless, absolute humidity can still provide a surrogate measure for indoor air moisture and temperature[22](https://www.nature.com/articles/s41598-022-19898-8#ref-CR22 "Marr, L. C., Tang, J. W., Van Mullekom, J. & Lakdawala, S. S. Mechanistic insights into the effect of humidity on airborne influenza virus survival, transmission and incidence. J. R. Soc. Interface 16, 20180298 (2019).").

Initial efforts to slow the spread of COVID-19 focused on reducing contacts between individuals through social-distancing measures such as large-scale lockdowns, which were significantly associated with reductions in cases[23](https://www.nature.com/articles/s41598-022-19898-8#ref-CR23 "Badr, H. S. et al. Association between mobility patterns and COVID-19 transmission in the USA: A mathematical modelling study. Lancet Infect. Dis. 20, 1247–1254 (2020)."). However, as the initial lockdowns were lifted and the movement of individuals increased, the correlation between mobility and case growth rates weakened overall[24](https://www.nature.com/articles/s41598-022-19898-8#ref-CR24 "Gatalo, O., Tseng, K., Hamilton, A., Lin, G. & Klein, E. Associations between phone mobility data and COVID-19 cases. Lancet Infect. Dis. 21, e111 (2020)."), though upticks in cases were associated with increased mobility during national holidays[25](https://www.nature.com/articles/s41598-022-19898-8#ref-CR25 "Aragão, D. P., dos Santos, D. H., Mondini, A. & Gonçalves, L. M. G. National holidays and social mobility behaviors: Alternatives for forecasting COVID-19 deaths in Brazil. Int. J. Environ. Res. Public Health 18, 11595 (2021)."). During the months of 2020 and 2021 some counties and states saw increases in cases, while others observed decreases without corresponding increases in movement by any metric. Thus, other factors, including environmental factors, must also be considered as important transmission drivers.

Analyses of the factors influencing COVID-19 have used either climate data[21](https://www.nature.com/articles/s41598-022-19898-8#ref-CR21 "Sajadi, M. M. et al. Temperature, humidity, and latitude analysis to estimate potential spread and seasonality of coronavirus disease 2019 (COVID-19). JAMA Netw. Open 3, e2011834 (2020)."), [26](https://www.nature.com/articles/s41598-022-19898-8#ref-CR26 "Wang, J. et al. High temperature and high humidity reduce the transmission of COVID-19. SSRN                    https://doi.org/10.2139/ssrn.3551767                                     (2020)."), [27](https://www.nature.com/articles/s41598-022-19898-8#ref-CR27 "Qi, H. et al. COVID-19 transmission in Mainland China is associated with temperature and humidity: A time-series analysis. Sci. Total Environ. 728, 138778 (2020)."), [28](https://www.nature.com/articles/s41598-022-19898-8#ref-CR28 "Xie, J. & Zhu, Y. Association between ambient temperature and COVID-19 infection in 122 cities from China. Sci. Total Environ. 724, 138201 (2020).") or human mobility data[23](https://www.nature.com/articles/s41598-022-19898-8#ref-CR23 "Badr, H. S. et al. Association between mobility patterns and COVID-19 transmission in the USA: A mathematical modelling study. Lancet Infect. Dis. 20, 1247–1254 (2020)."), but no study to our knowledge has considered changes in both climate and human mobility on COVID-19 outbreaks in the United States. Preliminary studies have investigated these effects in China but did not consider varying sensitivities to humidity for different climatological regimes, leading to a weaker detection of humidity impacts on transmission risks in areas with higher variations of humidity[29](https://www.nature.com/articles/s41598-022-19898-8#ref-CR29 "Poirier, C. et al. The role of environmental factors on transmission rates of the COVID-19 outbreak: An initial assessment in two spatial scales. Sci. Rep. 10, 17002 (2020)."). Understanding the potential for climatic factors to increase transmission in the fall and winter is crucial for developing policies to combat the spread of SARS-CoV-2. While the interaction between environmental factors and human encounters is complex, accounting for this relationship is necessary for determining appropriate policies that will be effective at reducing transmissions. Furthermore, indoor gatherings typically increase in frequency and size in the winter and are one of the largest risk factors for transmission[7](https://www.nature.com/articles/s41598-022-19898-8#ref-CR7 "de Man, P. et al. Outbreak of coronavirus disease 2019 (COVID-19) in a nursing home associated with aerosol transmission as a result of inadequate ventilation. Clin. Infect. Dis.                    https://doi.org/10.1093/cid/ciaa1270                                     (2021)."), [30](https://www.nature.com/articles/s41598-022-19898-8#ref-CR30 "Bhagat, R. K., Wykes, M. S. D., Dalziel, S. B. & Linden, P. F. Effects of ventilation on the indoor spread of COVID-19. J. Fluid Mech.                    https://doi.org/10.1017/jfm.2020.720                                     (2020)."). Therefore, greater understanding regarding the added risk of weather changes is needed to aid future decisions on restricting gatherings or implementing mandates for protective face coverings. In this study, we assessed the relative impact of absolute humidity and human mobility in different climatological regimes on reported cases of COVID-19 in the US.

## Results

### Partitioning climatological regimes

The US is geographically large and encompasses several different climatological regimes with varying absolute humidity trends. We partitioned all 3137 US counties into six exclusive clusters (Fig. [1](https://www.nature.com/articles/s41598-022-19898-8#Fig1)) ranked by average absolute humidity (AH) using a dynamic time warping (DTW) algorithm which considers both magnitude and functional trends of AH (see “ [Methods](https://www.nature.com/articles/s41598-022-19898-8#Sec8)”). The cluster with the lowest average AH was primarily located in the western region of the US, while the region with the highest average AH was located on the southern coast bordering the Gulf of Mexico. Large changes of humidity were seen in clusters High 1 and High 2 which, respectively, includes variances of 26.9 and 30.6 g/m3 (see Fig. [S1](https://www.nature.com/articles/s41598-022-19898-8#MOESM1)), while Low 1 and Low 2 humidity clusters had a variance of 4.5 and 14.2 g/m3.

**Figure 1**

![Figure 1](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-022-19898-8/MediaObjects/41598_2022_19898_Fig1_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-022-19898-8/figures/1)

( **A**) Map of US Counties and their respective absolute humidity clusters. Each county is colored based on their cluster. Counties that are included in the regression analysis are indicated by a darker shade. The clustering analysis was conducted using a partitional algorithm that utilized dynamic time warping (DTW) to measure similarity between absolute humidity profiles of 3137 counties in the United States. Expectantly, the clustering of absolute humidity is related to the geography of the counties which serves as a proxy for regional weather patterns and different climatological regimes. ( **B**) The cross-sectional smoothed mean of human encounter absolute humidity, and new case per 10,000 people trends for each cluster group of the 497 counties analyzed in the regression analysis. Map was generated using the ggplot package[31](https://www.nature.com/articles/s41598-022-19898-8#ref-CR31 "Wickham, H. ggplot2: Elegant Graphics for Data Analysis (Springer-Verlag, 2016).") in R.

### Associations between humidity and cases rates

We conducted a regression on counties with more than 50,000 people using a generalized linear model (GLM) and controlling for individual movement and behavior with a metric from mobile phone data of visits to non-essential businesses (see Methods), we found that increases in AH were significantly negatively associated with cases per 100,000 of COVID-19 in all the non-high humidity regions (Table [1](https://www.nature.com/articles/s41598-022-19898-8#Tab1)). We found that counties that belong to the least humid clusters, Low 1 and Low 2, had a 1 g/m3 increase in AH was associated with an average decrease of 14 percent reduction in cases over the entire duration, while the most humid clusters (High 1 and High 2) had a decrease of 4 percent in cases. The largest associations were seen in counties predominantly in the Rocky Mountains (Low 1; 20% decrease in daily cases), Upper Midwest/Northwest (Mid 1; 12% decrease in daily cases), West Coast/Texas/Northeast (Mid 2; 16% decrease in daily cases), and a region stretching along the western edge of the Midwest down to Texas (Low 2; 8% decrease in daily cases). Small but significant effects were detected in two high humidity clusters, both located in the southern region of the US (High 1 and High 2), with respective reductions of 6% and 1% in daily cases with a 1 g/m3 increase in AH.

**Table 1 Untransformed GLM coefficient estimates for the entire study period.**

[Full size table](https://www.nature.com/articles/s41598-022-19898-8/tables/1)

The overall associations between AH and COVID-19 cases were negatively correlated when disaggregated across the time periods (Tables [2](https://www.nature.com/articles/s41598-022-19898-8#Tab2) and [3](https://www.nature.com/articles/s41598-022-19898-8#Tab3)). The regression showed that AH had strong associations in the Mid 2 cluster, located in West Coast/Texas/Northeast, during the spring and summer months of 2020 (Table [2](https://www.nature.com/articles/s41598-022-19898-8#Tab2)). In the fall of 2020 and spring of 2021, AH associations were generally stronger in counties from Mid 2 and High 1 clusters, which are in the West Coast, Texas, Northeast and Southern regions of the US (Table [3](https://www.nature.com/articles/s41598-022-19898-8#Tab3)).

**Table 2 Untransformed GLM coefficient estimates for the 2020 spring to fall period.**

[Full size table](https://www.nature.com/articles/s41598-022-19898-8/tables/2)

**Table 3 Untransformed GLM coefficient estimates for the 2020 winter and 2021 spring seasons.**

[Full size table](https://www.nature.com/articles/s41598-022-19898-8/tables/3)

### Associations between movement and case rates

In general, movement effects on daily cases are larger than absolute humidity effects, with visits to retail and recreation positively associated with new COVID-19 cases in most of the clusters (Table [1](https://www.nature.com/articles/s41598-022-19898-8#Tab1)). Mobility trends for retail & recreation and grocery stores & pharmacies had a larger positive effect during the earlier phase of the pandemic for most clusters (March 10 to September 30, 2020) compared to the later phase spanning from October 1, 2020 to March 1, 2021. The residential mobility trend was associated with a decrease in new cases in most clusters during the earlier phase of the pandemic (Table [2](https://www.nature.com/articles/s41598-022-19898-8#Tab2)), while having a positive effect on daily cases during the later phase (Table [3](https://www.nature.com/articles/s41598-022-19898-8#Tab3)).

### Detecting multicollinearity between movement and absolute humidity

To understand the collinearity of the combined regressions shown in Tables [1](https://www.nature.com/articles/s41598-022-19898-8#Tab1), [2](https://www.nature.com/articles/s41598-022-19898-8#Tab2) and [3](https://www.nature.com/articles/s41598-022-19898-8#Tab3), we conducted robustness checks with additional regressions that included the AH and the mobility trends separately (See Tables [S1](https://www.nature.com/articles/s41598-022-19898-8#MOESM1)– [S18](https://www.nature.com/articles/s41598-022-19898-8#MOESM1)). Additionally, we calculated the Generalized Variational Inflation Factor (GVIF) for the regressions in our robustness checks. Workplaces and Residential Mobility Trends were the least collinear with other independent variables (absolute humidity, immunity factor, and previous 14-day caseload) supported by GVIF values less than 2. Mobility trends in Retail and Recreation Areas and Grocery Stores and Pharmacies were mostly non-collinear with few exceptions with GVIF values ranging between with a mean of 1.53 (range: 1.15–2.30) and 1.65 (1.28–2.63). And finally, Transit Stations and Parks demonstrated the most collinearity with mean GVIF values of 2.15 (1.45–3.71) and 2.01 (1.56–2.83).

## Discussion

As the COVID-19 epidemic continues in the US and given the surge of COVID-19 in the winter seasons, there is renewed interest in understanding the relationship between outbreaks and seasonal changes, especially climatological factors related to outdoor and indoor humidity. This is not the first study to investigate humidity impacts on transmission, which been associated with increased transmission of respiratory pathogens (e.g., influenza) and SARS-CoV-2. While SARS-CoV-2 is a novel human virus, other pandemic coronaviruses (e.g., MERS-CoV and SARS-CoV-1)[9](https://www.nature.com/articles/s41598-022-19898-8#ref-CR9 "Shaman, J. & Kohn, M. Absolute humidity modulates influenza survival, transmission, and seasonality. Proc. Natl. Acad. Sci. 106, 3243–3248 (2009)."), [32](https://www.nature.com/articles/s41598-022-19898-8#ref-CR32 "Gardner, E. G. et al. A case-crossover analysis of the impact of weather on primary cases of Middle East respiratory syndrome. BMC Infect. Dis. 19, 113 (2019)."), [33](https://www.nature.com/articles/s41598-022-19898-8#ref-CR33 "Chan, K. H. et al. The effects of temperature and relative humidity on the viability of the SARS coronavirus. Adv. Virol. 2011, 1–7 (2011)."), [34](https://www.nature.com/articles/s41598-022-19898-8#ref-CR34 "Yuan, J. et al. A climatologic investigation of the SARS-CoV outbreak in Beijing, China. Am. J. Infect. Control 34, 234–236 (2006)."), [35](https://www.nature.com/articles/s41598-022-19898-8#ref-CR35 "Altamimi, A. & Ahmed, A. E. Climate factors and incidence of Middle East respiratory syndrome coronavirus. J. Infect. Public Health 13, 704–708 (2020).") have also been associated with increased transmission in the winter, thus suggesting similar implications for SARS-CoV-2. Here, we found that the relative effect of absolute humidity on transmissions has so far been significant and was greatest in the Western, upper Midwest, and Northeast regions of the United States, which were clustered into the driest climatological regimes. These results support the hypothesis that falling rates of absolute humidity magnify the transmission risk of SARS-CoV-2, particularly in regions that are more arid and dry[36](https://www.nature.com/articles/s41598-022-19898-8#ref-CR36 "AntonyAroulRaj, V., Velraj, R. & Haghighat, F. The contribution of dry indoor built environment on the spread of Coronavirus: Data from various Indian states. Sustain. Cities Soc. 62, 102371 (2020)."). This effect was less noticeable for more humid regions, such as the coastal and southern counties of the US (Fig. [2](https://www.nature.com/articles/s41598-022-19898-8#Fig2)).

**Figure 2**

![Figure 2](https://media.springernature.com/lw685/springer-static/image/art%3A10.1038%2Fs41598-022-19898-8/MediaObjects/41598_2022_19898_Fig2_HTML.png)The alternative text for this image may have been generated using AI.

[Full size image](https://www.nature.com/articles/s41598-022-19898-8/figures/2)

The average daily new cases per 100,000 people plotted against the average Google Mobility Measure of 497 counties for the entire study duration. The plots are organized by type of movement and cluster group. For each plot, we added a simple linear trend line with shaded standard errors.

The effects of behavior and nonpharmaceutical interventions (NPI) are observed in our analysis when we disaggregate the analysis between the early and later phases of the pandemic. In the early phase of the pandemic, we see that an increase in mobility trends for retail & recreation resulted in an increase in daily cases, which measures visits to restaurants, cafes, shopping centers, theme parks, museums, libraries, and movie theaters. While in the later stages during the fall and winter of 2020, retail & recreation mobility had a lesser effect since many of those establishments were closed due to NPI policies. Furthermore, increases in residential mobility played a larger role in transmission, especially during the winter holidays when travel between residential homes occurred at a higher incidence.

The relationship between humidity and transmission is not fully clear, but several studies have shown that as absolute humidity decreases, survival times for enveloped viruses increase nonlinearly, including other coronaviruses[9](https://www.nature.com/articles/s41598-022-19898-8#ref-CR9 "Shaman, J. & Kohn, M. Absolute humidity modulates influenza survival, transmission, and seasonality. Proc. Natl. Acad. Sci. 106, 3243–3248 (2009)."), [22](https://www.nature.com/articles/s41598-022-19898-8#ref-CR22 "Marr, L. C., Tang, J. W., Van Mullekom, J. & Lakdawala, S. S. Mechanistic insights into the effect of humidity on airborne influenza virus survival, transmission and incidence. J. R. Soc. Interface 16, 20180298 (2019)."), [37](https://www.nature.com/articles/s41598-022-19898-8#ref-CR37 "McDevitt, J., Rudnick, S., First, M. & Spengler, J. Role of absolute humidity in the inactivation of influenza viruses on stainless steel surfaces at elevated temperatures. Appl. Environ. Microbiol. 76, 3943–3947 (2010)."), [38](https://www.nature.com/articles/s41598-022-19898-8#ref-CR38 "Shaman, J., Goldstein, E. & Lipsitch, M. Absolute humidity and pandemic versus epidemic influenza. Am. J. Epidemiol. 173, 127–135 (2011)."). Our findings support the hypothesis of a nonlinear relationship since the log-linear effects between humidity and case growth varied between climatological regimes. Our stratified regression and Fig. [2](https://www.nature.com/articles/s41598-022-19898-8#Fig2) show that different climatological regimes have different sensitivities to humidity changes. The increased survival of the virus in lower AH may be compounded by increased binding capacity, thereby enhancing the potential infectivity of the virus[39](https://www.nature.com/articles/s41598-022-19898-8#ref-CR39 "de la Noue, A. C. et al. Absolute humidity influences the seasonal persistence and infectivity of human norovirus. Appl. Environ. Microbiol. 80, 7196–7205 (2014)."). As AH falls, relative humidity indoors also decreases, which may increase susceptibility to airborne diseases[40](https://www.nature.com/articles/s41598-022-19898-8#ref-CR40 "Ahlawat, A., Wiedensohler, A. & Mishra, S. K. An overview on the role of relative humidity in airborne transmission of SARS-CoV-2 in indoor environments. Aerosol Air Qual. Res. 20, 1856–1861 (2020)."). This association suggests that increased humidification of indoor air in high transmission settings may help decrease the burden of COVID-19.

Given that our results suggest COVID-19 cases will increase significantly during winters, areas where humidity typically falls earlier in the fall (e.g., the upper Midwest) are likely to see cases increase earlier. In contrast, more humid regions (e.g., Gulf Coast areas) will likely observe outbreaks later in the winter. However, the results demonstrate that mobility had a larger and significant impact on cases, particularly when humidity was unchanging in the summer. Consequently, falling temperatures and holiday celebrations are likely to increase the risk of people gathering in indoor spaces for longer durations, resulting in a surge of COVID-19 cases through the winter, given that there are no substantial changes in population immunity and behavior.

The prior influenza pandemic in 2009 is instructive here, as increased contact patterns that occurred in the fall likely combined with falling humidity to drive transmission, which resulted in the peak of infections occurring significantly earlier than other years. Given the uncertainty and nonlinear effects of humidity on transmission, increasing vaccination, proper social distancing, and improving healthcare capacities can potentially reduce the toll of the COVID-19 pandemic. In addition, the uncertainty regarding the role of children in transmission[41](https://www.nature.com/articles/s41598-022-19898-8#ref-CR41 "Qiu, H. et al. Clinical and epidemiological features of 36 children with coronavirus disease 2019 (COVID-19) in Zhejiang, China: An observational cohort study. Lancet Infect. Dis 20, 689–696 (2020)."), [42](https://www.nature.com/articles/s41598-022-19898-8#ref-CR42 "Kelvin, A. A. & Halperin, S. COVID-19 in children: The link in the transmission chain. Lancet Infect. Dis 20, 633–634 (2020)."), [43](https://www.nature.com/articles/s41598-022-19898-8#ref-CR43 "Viner, R. M. et al. School closure and management practices during coronavirus outbreaks including COVID-19: A rapid systematic review. Lancet Child Adolesc. Health 4, 397–404 (2020)."), who remain largely unvaccinated, suggests that proper precautions related to opening schools is warranted as the potential for transmission increases. While studies linking schools to outbreaks to date have been limited, few have occurred during the winter when transmission is higher.

We suspected that a relationship between human behavior and climate might exist which can cause variations in encounters. During winter months, the likelihood of being indoors increases especially in colder climates. To investigate this potential interaction, we conducted a collinear analysis. We can interpret this collinear analysis as residential and workplace movement patterns not being collinear with meteorological conditions (absolute humidity) and epidemiological factors (immunity factor and new cases per 100,000 (14-day Lag)). Retail/recreation and grocery/pharmacies are moderately collinear, while transit stations and parks were the most collinearly related to meteorological and epidemiological variables.

One limitation of this study includes changing social distancing dynamics and masking adherence between counties. We attempted to account for county-level heterogeneities using fixed effects for each county, but these are static effects. Furthermore, it is difficult to disentangle the epidemiological dynamics that cause exponential growth of cases. Events related to evacuation in natural disasters or mass-gatherings during the summer of 2020 that were not reflected in the Google Mobility Data[44](https://www.nature.com/articles/s41598-022-19898-8#ref-CR44 "Salas, R. N., Shultz, J. M. & Solomon, C. G. The climate crisis and Covid-19—A major threat to the pandemic response. N. Engl. J. Med. 383, e70 (2020).") may bias the analysis. Also, as with many COVID-19 analyses on retrospective data, the differences in testing rates at the county-level will result in varying detection rates of actual cases. Potential variations around vaccination efficacy for variants and within-host changes will impact the magnitude and exact timing of outbreaks[45](https://www.nature.com/articles/s41598-022-19898-8#ref-CR45 "Kronfeld-Schor, N. et al. Drivers of infectious disease seasonality: Potential implications for COVID-19. J. Biol. Rhythms 36, 35–54 (2021).").

Transmission of SARS-CoV-2 will likely increase during the winters in the United States and other temperate regions in the northern hemisphere due in part to falling humidity. Studies of prior viruses and preliminary studies of the SARS-CoV-2 virus underpin the theoretical connection between humidity and transmission of droplet and aerosols. Nevertheless, mobility is still a significant driver of transmission.

## Methods

### Study design

The United States is geographically large, and the timing and magnitude of changes in absolute humidity can vary widely across regions. In order to account for regional differences in humidity, we utilized a partitional clustering algorithm with dynamic time warping (DTW) similarity measurements[46](https://www.nature.com/articles/s41598-022-19898-8#ref-CR46 "Berndt, D. J. & Clifford, J. Using dynamic time warping to find patterns in time series. 12.") to classify the absolute humidity temporal profile for all observed counties into six exclusive clusters that are ranked based on average humidity. The clustering algorithm was implemented using the _dtw_ package in R[47](https://www.nature.com/articles/s41598-022-19898-8#ref-CR47 "Giorgino, T. Computing and visualizing dynamic time warping alignments in R : The dtw package. J. Stat. Softw.                    https://doi.org/10.18637/jss.v031.i07                                     (2009)."). These clusters are ranked from lowest to highest as _Low 1, Low 2, Mid 1, Mid 2, High 1,_ and _High 2._ Clustering allowed us to designate groups of counties based on temporal, climatological regimes and to stratify different absolute humidity patterns, which reduces group-level effects and enhances the independence of the data points. The DTW clustering of absolute humidity was conducted on a larger set of 3,137 counties. In the regression analysis, we included data from a subset of counties that had more than twenty cumulative confirmed cases and a population of more than 50,000 people. We excluded any days with fewer than 20 cumulative confirmed cases within each county because early transmission dynamics had a high rate of undetected cases[48](https://www.nature.com/articles/s41598-022-19898-8#ref-CR48 "Silverman, J. D., Hupert, N. & Washburne, A. D. Using influenza surveillance networks to estimate state-specific prevalence of SARS-CoV-2 in the United States. Sci. Transl. Med.                    https://doi.org/10.1126/scitranslmed.abc1126                                     (2020)."), making the data unreliable for this analysis. The final dataset used in the regression analysis included 497 counties, where separate panel data GLM was conducted on counties in each cluster (NLow1 = 39, NLow 2 = 42, NMid1 = 118, NMid2 = 108, NHigh1 = 78, and NHigh2 = 105). We assessed the results of the model over the entirety of the dataset and two time periods in 2020–2021: (1) the entire duration of the dataset (March 10, 2020 to March 1, 2021), (2) spring and summer when humidity increases (March 10, 2020 to September 30, 2020), and (3) the fall and winter months when humidity decreases to its lowest point (October 1, 2020 to March 1, 2021).

### Data sources

Confirmed case data were extracted from the Johns Hopkins Center for Systems Science and Engineering[1](https://www.nature.com/articles/s41598-022-19898-8#ref-CR1 "Dong, E., Du, H. & Gardner, L. An interactive web-based dashboard to track COVID-19 in real time. Lancet Infect. Dis. 20, 533–534 (2020).") for each county. Population data were obtained from the US Census Bureau[49](https://www.nature.com/articles/s41598-022-19898-8#ref-CR49 "2018 ACS 1-year Estimates. The United States Census Bureau                    https://www.census.gov/programs-surveys/acs/technical-documentation/table-and-geography-changes/2018/1-year.html                                    .") for 3,137 counties from March 10, 2020 to March 1, 2021. Daily cases were obtained from the confirmed case count by taking a simple difference between the days. Any data incongruencies, such as negative case counts, were omitted in our analysis.

Daily average absolute humidity for each US county, excluding territories, was calculated using temperature and dewpoint data from the National Centers for Environmental Information[50](https://www.nature.com/articles/s41598-022-19898-8#ref-CR50 "National Centers for Environmental Information (NCEI).                    https://www.ncei.noaa.gov/                                    .") at the National Oceanic and Atmospheric Administration (NOAA). Time series data for the year 2020 from US weather stations were acquired from the NOAA Global Summary of the Day Index[51](https://www.nature.com/articles/s41598-022-19898-8#ref-CR51 "Global Surface Summary of the Day—GSOD—NOAA Data Catalog.                    https://data.noaa.gov/dataset/dataset/global-surface-summary-of-the-day-gsod                                    ."). Weather stations were mapped using latitude and longitude to corresponding counties using the Federal Communications Commission (FCC) Census Block API[52](https://www.nature.com/articles/s41598-022-19898-8#ref-CR52 "Census Block Conversions API. Federal Communications Commission                    https://www.fcc.gov/census-block-conversions-api                                     (2011)."). For counties without a weather station, we used data from the nearest station, which was calculated based on distance from the county’s spatial centroid using the haversine formula. In cases where counties contained multiple stations, data were averaged across all stations in a county. Absolute humidity was calculated using average daily temperature and average daily dew point (see Alduchov and Eskridge[53](https://www.nature.com/articles/s41598-022-19898-8#ref-CR53 "Alduchov, O. A. & Eskridge, R. E. Improved Magnus form approximation of saturation vapor pressure. J. Appl. Meteorol. 35, 601–609 (1996).")).

Data on mobility from March 10, 2020 to March 1, 2021 was obtained from the Google COVID-19 Community Mobility Reports[54](https://www.nature.com/articles/s41598-022-19898-8#ref-CR54 "Google LLC. COVID-19 Community Mobility Report. COVID-19 Community Mobility Report                    https://www.google.com/covid19/mobility?hl=en                                    ."). We specifically utilized the metric that measures visits to grocery stores & pharmacies, parks, transit stations, retail & recreation, residential, and workplaces by comparing the median rate on the county-level to a 5-week period Jan 3–Feb 6, 2020. The measure was calculated as the percent difference from before policy interventions (e.g., shelter-in-place orders) began to impact movement. This temporal measure allowed us to compare movement differences across counties.

### Statistical analysis

For each humidity cluster that was classified using the DTW algorithm, we conducted three multivariate regressions using a generalized linear model (GLM) that assessed the time-weighted association between absolute humidity and non-essential visits with the number of new coronavirus cases (Eqs. [1](https://www.nature.com/articles/s41598-022-19898-8#Equ1)– [3](https://www.nature.com/articles/s41598-022-19898-8#Equ3)). The GLM regression results in Tables [1](https://www.nature.com/articles/s41598-022-19898-8#Tab1), [2](https://www.nature.com/articles/s41598-022-19898-8#Tab2) and [3](https://www.nature.com/articles/s41598-022-19898-8#Tab3) are described in the following equation,

$$\\begin{aligned} \\log \\left( {Y\_{it} } \\right) = & \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{4} RR\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{5} GP\_{{i\\left( {t - \\delta } \\right)}} \\\ & + \\beta\_{6} PK\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{7} TS\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{8} WP\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{9} RD\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it} \\\ \\end{aligned}$$

(1)


where _Y_ _it_, is the number of daily COVID-19 cases for county _i_ at time _t_, log( _N_) is an offset term to control for population-size, and _α_ is the intercept. In order to account for population immunity and exponential growth dynamics, we added the independent variables cumulative cases per 100,000, _IM_ _t_, and lagged daily cases per 100,000, _y_ _i(t-δ)_ to the regression models. Absolute humidity, _AH_ _i(t-δ)_ is smoothed using a 7-day moving average and lagged by _δ_ days. Google mobility trends to retail and recreation, _RR_ _i(t-δ)_, grocery and pharmacies, _GP_ _i(t-δ)_, parks, _PK_ _i(t-δ)_, transit stations, _TS_ _i(t-δ)_, workplaces, _WP_ _i(t-δ)_, residential places, _RD_ _i(t-δ)_, are smoothed using a 7-day moving average, lagged by _δ_ days, and rescaled and centered on the mean. Fixed effects γi for each county were added to capture unobserved heterogeneities between counties. For our study, we assumed that the lag length _δ_ was equal to 14 days, which is based on previous studies investigating lagged effects due to the incubation period of COVID-19[55](https://www.nature.com/articles/s41598-022-19898-8#ref-CR55 "Lauer, S. A. et al. The incubation period of coronavirus disease 2019 (COVID-19) from publicly reported confirmed cases: Estimation and application. Ann. Intern. Med. 172, 577–582 (2020)."). As our outcome variable was daily cases, we modeled the variable as a Poisson distributed random variable with a log-transformed link function. Standard errors were calculated for the estimated linear coefficients _β_.

We conducted additional regressions on the absolute humidity and mobility measures as predictors individually to test for robustness. Specifically, we fit a GLM with absolute humidity for each humidity cluster and one measure from rescaled Google COVID-19 Community Mobility as linear predictors for new daily cases, as described in Eqs. ( [2](https://www.nature.com/articles/s41598-022-19898-8#Equ2)) to ( [8](https://www.nature.com/articles/s41598-022-19898-8#Equ3)).

$$\\log \\left( {Y\_{it} } \\right) = \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it}$$

(2)


$$\\log \\left( {Y\_{it} } \\right) = \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{4} RR\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it}$$

(3)


$$\\log \\left( {Y\_{it} } \\right) = \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{4} GP\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it}$$

(4)


$$\\log \\left( {Y\_{it} } \\right) = \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{4} PK\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it}$$

(5)


$$\\log \\left( {Y\_{it} } \\right) = \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{4} TS\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it}$$

(6)


$$\\log \\left( {Y\_{it} } \\right) = \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{4} RD\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it}$$

(7)


$$\\log \\left( {Y\_{it} } \\right) = \\log \\left( N \\right) + \\alpha + \\beta\_{1} IM\_{t} + \\beta\_{2} y\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{3} AH\_{{i\\left( {t - \\delta } \\right)}} + \\beta\_{4} WP\_{{i\\left( {t - \\delta } \\right)}} + \\gamma\_{i} + \\epsilon\_{it}$$

(8)


To demonstrate robustness in the coefficient estimates, the coefficients in the combined regression analyses with absolute humidity and all mobility trends (Eq. ( [1](https://www.nature.com/articles/s41598-022-19898-8#Equ1))) were compared to the regression coefficients for absolute humidity and each mobility trend (Eqs. ( [2](https://www.nature.com/articles/s41598-022-19898-8#Equ2))–( [8](https://www.nature.com/articles/s41598-022-19898-8#Equ3))). The analysis using GLM was conducted using the _stats_ package in R (Version 4.0.2). All untransformed coefficient estimates are located in (Tables [1](https://www.nature.com/articles/s41598-022-19898-8#Tab1), [2](https://www.nature.com/articles/s41598-022-19898-8#Tab2) and [3](https://www.nature.com/articles/s41598-022-19898-8#Tab3)). In the main text, we reported the logit-transformed estimates as relative change in cases per unit increase (1 g/m3) of absolute humidity. Given the log-linear relationship in a Poisson regression between the covariates and response variable, we can calculate the percent change in daily cases for a unit increase of a covariate to be equal to exp ( _β_) − 1\. For example, if β = − 0.112 for absolute humidity, we would state that there is a 9% (= exp (− 0.112) − 1) reduction for 1 g/m3 increase in absolute humidity. To verify that mulicollinearity is not a major issue, we conducted a collinearity analysis by calculating the Generalized Variational Inflation Factor (GVIF) for all regressions, which are listed in Table [S19](https://www.nature.com/articles/s41598-022-19898-8#MOESM1).

In addition to running a GLM regression, we also discretized the data based on months for each humidity cluster and calculated the Pearson correlation coefficient for absolute humidity and Google Mobility Trends against new cases (Fig. [S2](https://www.nature.com/articles/s41598-022-19898-8#MOESM1)). Stationarity was checked for absolute humidity and Google mobility trends using the Levin-Lin-Chu unit-root test for unbalanced panel data for the three periods that were analyzed aforementioned regressions. Results for the stationarity are listed in Table [S20](https://www.nature.com/articles/s41598-022-19898-8#MOESM1) in the supplement.

We tested for robustness and externally validated our regressions by conducting additional analysis using K-folds cross-validation. We validated the coefficient estimation of all the GLMs mentioned previously by showing that the relative effect size for each regression was similar. The analysis was conducted over 100 folds or iterations with separate training and test sets derived from a subset of the county-level data. We used test sets for each fold where the mean square error (MSE) was calculated for each fit and shown in Table [S22](https://www.nature.com/articles/s41598-022-19898-8#MOESM1) in the supplement. In order to minimize overfitting, we also excluded county-level fixed effects in our cross-validation analysis. Additionally, we show the 95% confidence intervals of all parameter estimations using the GLM model that includes all variables in Table [S23](https://www.nature.com/articles/s41598-022-19898-8#MOESM1).

## Data availability

The data that support the findings of this study are openly available through the Johns Hopkins Center for Systems Science and Engineering, Unacast Social Distancing Scorecard, and NOAA National Centers for Environmental Information. Population data can be found through the US Census Bureau Website. All input data and code used to conduct the analysis and generate figures are also available on Github at [https://github.com/CDDEP-DC/COVID-Humidity-Mobility-GAM](https://github.com/CDDEP-DC/COVID-Humidity-Mobility-GAM).

## References

01. Dong, E., Du, H. & Gardner, L. An interactive web-based dashboard to track COVID-19 in real time. _Lancet Infect. Dis._ **20**, 533–534 (2020).

    [Article](https://doi.org/10.1016%2FS1473-3099%2820%2930120-1) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXksVaisbs%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=An%20interactive%20web-based%20dashboard%20to%20track%20COVID-19%20in%20real%20time&journal=Lancet%20Infect.%20Dis.&doi=10.1016%2FS1473-3099%2820%2930120-1&volume=20&pages=533-534&publication_year=2020&author=Dong%2CE&author=Du%2CH&author=Gardner%2CL)

02. Liu, J. _et al._ Community transmission of severe acute respiratory syndrome coronavirus 2, Shenzhen, China, 2020. _Emerg. Infect. Dis._ **26**, 1320–1323 (2020).

    [Article](https://doi.org/10.3201%2Feid2606.200239) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhtlaru7zL) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Community%20transmission%20of%20severe%20acute%20respiratory%20syndrome%20coronavirus%202%2C%20Shenzhen%2C%20China%2C%202020&journal=Emerg.%20Infect.%20Dis.&doi=10.3201%2Feid2606.200239&volume=26&pages=1320-1323&publication_year=2020&author=Liu%2CJ)

03. Chan, J.F.-W. _et al._ A familial cluster of pneumonia associated with the 2019 novel coronavirus indicating person-to-person transmission: A study of a family cluster. _The Lancet_ **395**, 514–523 (2020).

    [Article](https://doi.org/10.1016%2FS0140-6736%2820%2930154-9) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhs1Ojsro%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=A%20familial%20cluster%20of%20pneumonia%20associated%20with%20the%202019%20novel%20coronavirus%20indicating%20person-to-person%20transmission%3A%20A%20study%20of%20a%20family%20cluster&journal=The%20Lancet&doi=10.1016%2FS0140-6736%2820%2930154-9&volume=395&pages=514-523&publication_year=2020&author=Chan%2CJF-W)

04. CDC. Coronavirus Disease 2019 (COVID-19). _Centers for Disease Control and Prevention._ [https://www.cdc.gov/coronavirus/2019-ncov/more/scientific-brief-sars-cov-2.html](https://www.cdc.gov/coronavirus/2019-ncov/more/scientific-brief-sars-cov-2.html) (2020).

05. Tang, S. _et al._ Aerosol transmission of SARS-CoV-2? evidence, prevention and control. _Environ. Int._ **144**, 106039 (2020).

    [Article](https://doi.org/10.1016%2Fj.envint.2020.106039) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhs1CrsbnO) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Aerosol%20transmission%20of%20SARS-CoV-2%3F%20evidence%2C%20prevention%20and%20control&journal=Environ.%20Int.&doi=10.1016%2Fj.envint.2020.106039&volume=144&publication_year=2020&author=Tang%2CS)

06. Ma, J. _et al._ Coronavirus disease 2019 patients in earlier stages exhaled millions of severe acute respiratory syndrome coronavirus 2 per hour. _Clin. Infect. Dis._ [https://doi.org/10.1093/cid/ciaa1283](https://doi.org/10.1093/cid/ciaa1283) (2021).

    [Article](https://doi.org/10.1093%2Fcid%2Fciaa1283) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34791120) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC9187317) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Coronavirus%20disease%202019%20patients%20in%20earlier%20stages%20exhaled%20millions%20of%20severe%20acute%20respiratory%20syndrome%20coronavirus%202%20per%20hour&journal=Clin.%20Infect.%20Dis.&doi=10.1093%2Fcid%2Fciaa1283&publication_year=2021&author=Ma%2CJ)

07. de Man, P. _et al._ Outbreak of coronavirus disease 2019 (COVID-19) in a nursing home associated with aerosol transmission as a result of inadequate ventilation. _Clin. Infect. Dis._ [https://doi.org/10.1093/cid/ciaa1270](https://doi.org/10.1093/cid/ciaa1270) (2021).

    [Article](https://doi.org/10.1093%2Fcid%2Fciaa1270) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=33300564) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8406883) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Outbreak%20of%20coronavirus%20disease%202019%20%28COVID-19%29%20in%20a%20nursing%20home%20associated%20with%20aerosol%20transmission%20as%20a%20result%20of%20inadequate%20ventilation&journal=Clin.%20Infect.%20Dis.&doi=10.1093%2Fcid%2Fciaa1270&publication_year=2021&author=Man%2CP)

08. Rahman, H. S. _et al._ The transmission modes and sources of COVID-19: A systematic review. _Int. J. Surg. Open_ **26**, 125–136 (2020).

    [Article](https://doi.org/10.1016%2Fj.ijso.2020.08.017) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20transmission%20modes%20and%20sources%20of%20COVID-19%3A%20A%20systematic%20review&journal=Int.%20J.%20Surg.%20Open&doi=10.1016%2Fj.ijso.2020.08.017&volume=26&pages=125-136&publication_year=2020&author=Rahman%2CHS)

09. Shaman, J. & Kohn, M. Absolute humidity modulates influenza survival, transmission, and seasonality. _Proc. Natl. Acad. Sci._ **106**, 3243–3248 (2009).

    [Article](https://doi.org/10.1073%2Fpnas.0806852106) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2009PNAS..106.3243S) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BD1MXivF2js7w%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Absolute%20humidity%20modulates%20influenza%20survival%2C%20transmission%2C%20and%20seasonality&journal=Proc.%20Natl.%20Acad.%20Sci.&doi=10.1073%2Fpnas.0806852106&volume=106&pages=3243-3248&publication_year=2009&author=Shaman%2CJ&author=Kohn%2CM)

10. Wu, Y. _et al._ Effects of temperature and humidity on the daily new cases and new deaths of COVID-19 in 166 countries. _Sci. Total Environ._ **729**, 139051 (2020).

    [Article](https://doi.org/10.1016%2Fj.scitotenv.2020.139051) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020ScTEn.729m9051W) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXosVymt7o%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Effects%20of%20temperature%20and%20humidity%20on%20the%20daily%20new%20cases%20and%20new%20deaths%20of%20COVID-19%20in%20166%20countries&journal=Sci.%20Total%20Environ.&doi=10.1016%2Fj.scitotenv.2020.139051&volume=729&publication_year=2020&author=Wu%2CY)

11. Kato, M., Sakihama, T., Kinjo, Y., Itokazu, D. & Tokuda, Y. _Effect of Climate on COVID-19 Incidence: A Cross-Sectional Study in Japan_. [https://papers.ssrn.com/abstract=3612114](https://papers.ssrn.com/abstract=3612114). [https://doi.org/10.2139/ssrn.3612114](https://doi.org/10.2139/ssrn.3612114) (2020).

12. Christophi, C. A. _et al. Ambient Temperature and Subsequent COVID-19 Mortality in the OECD Countries and Individual United States_. [https://papers.ssrn.com/abstract=3612112](https://papers.ssrn.com/abstract=3612112). [https://doi.org/10.2139/ssrn.3612112](https://doi.org/10.2139/ssrn.3612112) (2020).

13. Meyer, A., Sadler, R., Faverjon, C., Cameron, A. R. & Bannister-Tyrrell, M. Evidence that higher temperatures are associated with a marginally lower incidence of COVID-19 cases. _Front. Public Health_ [https://doi.org/10.3389/fpubh.2020.00367](https://doi.org/10.3389/fpubh.2020.00367) (2020).

    [Article](https://doi.org/10.3389%2Ffpubh.2020.00367) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=33224922) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7674395) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Evidence%20that%20higher%20temperatures%20are%20associated%20with%20a%20marginally%20lower%20incidence%20of%20COVID-19%20cases&journal=Front.%20Public%20Health&doi=10.3389%2Ffpubh.2020.00367&publication_year=2020&author=Meyer%2CA&author=Sadler%2CR&author=Faverjon%2CC&author=Cameron%2CAR&author=Bannister-Tyrrell%2CM)

14. Steiger, E., Mussgnug, T. & Kroll, L. E. Causal analysis of COVID-19 observational data in German districts reveals effects of mobility, awareness, and temperature. _medRxiv_ [https://doi.org/10.1101/2020.07.15.20154476](https://doi.org/10.1101/2020.07.15.20154476) (2020).

    [Article](https://doi.org/10.1101%2F2020.07.15.20154476) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Causal%20analysis%20of%20COVID-19%20observational%20data%20in%20German%20districts%20reveals%20effects%20of%20mobility%2C%20awareness%2C%20and%20temperature&journal=medRxiv&doi=10.1101%2F2020.07.15.20154476&publication_year=2020&author=Steiger%2CE&author=Mussgnug%2CT&author=Kroll%2CLE)

15. Kifer, D. _et al._ Effects of environmental factors on severity and mortality of COVID-19. _medRxiv_ [https://doi.org/10.1101/2020.07.11.20147157](https://doi.org/10.1101/2020.07.11.20147157) (2020).

    [Article](https://doi.org/10.1101%2F2020.07.11.20147157) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Effects%20of%20environmental%20factors%20on%20severity%20and%20mortality%20of%20COVID-19&journal=medRxiv&doi=10.1101%2F2020.07.11.20147157&publication_year=2020&author=Kifer%2CD)

16. Sehra, S. T., Salciccioli, J. D., Wiebe, D. J., Fundin, S. & Baker, J. F. Maximum daily temperature, precipitation, ultraviolet light, and rates of transmission of severe acute respiratory syndrome coronavirus 2 in the United States. _Clin. Infect. Dis._ [https://doi.org/10.1093/cid/ciaa681](https://doi.org/10.1093/cid/ciaa681) (2020).

    [Article](https://doi.org/10.1093%2Fcid%2Fciaa681) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32472936) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Maximum%20daily%20temperature%2C%20precipitation%2C%20ultraviolet%20light%2C%20and%20rates%20of%20transmission%20of%20severe%20acute%20respiratory%20syndrome%20coronavirus%202%20in%20the%20United%20States&journal=Clin.%20Infect.%20Dis.&doi=10.1093%2Fcid%2Fciaa681&publication_year=2020&author=Sehra%2CST&author=Salciccioli%2CJD&author=Wiebe%2CDJ&author=Fundin%2CS&author=Baker%2CJF)

17. Mecenas, P., da Rosa Moreira Bastos, R. T., Vallinoto, A. C. R. & Normando, D. Effects of temperature and humidity on the spread of COVID-19: A systematic review. _PLOS ONE_ **15**, e0238339 (2020).

    [Article](https://doi.org/10.1371%2Fjournal.pone.0238339) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhvFahs7jK) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Effects%20of%20temperature%20and%20humidity%20on%20the%20spread%20of%20COVID-19%3A%20A%20systematic%20review&journal=PLOS%20ONE&doi=10.1371%2Fjournal.pone.0238339&volume=15&publication_year=2020&author=Mecenas%2CP&author=Rosa%20Moreira%20Bastos%2CRT&author=Vallinoto%2CACR&author=Normando%2CD)

18. Aragão, D. P. _et al._ Multivariate data driven prediction of COVID-19 dynamics: Towards new results with temperature, humidity and air quality data. _Environ. Res._ **204**, 112348 (2022).

    [Article](https://doi.org/10.1016%2Fj.envres.2021.112348) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Multivariate%20data%20driven%20prediction%20of%20COVID-19%20dynamics%3A%20Towards%20new%20results%20with%20temperature%2C%20humidity%20and%20air%20quality%20data&journal=Environ.%20Res.&doi=10.1016%2Fj.envres.2021.112348&volume=204&publication_year=2022&author=Arag%C3%A3o%2CDP)

19. Yuan, S., Jiang, S.-C. & Li, Z.-L. Do humidity and temperature impact the spread of the novel coronavirus?. _Front. Public Health_ [https://doi.org/10.3389/fpubh.2020.00240](https://doi.org/10.3389/fpubh.2020.00240) (2020).

    [Article](https://doi.org/10.3389%2Ffpubh.2020.00240) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=33575242) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7554513) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Do%20humidity%20and%20temperature%20impact%20the%20spread%20of%20the%20novel%20coronavirus%3F&journal=Front.%20Public%20Health&doi=10.3389%2Ffpubh.2020.00240&publication_year=2020&author=Yuan%2CS&author=Jiang%2CS-C&author=Li%2CZ-L)

20. Lolli, S., Chen, Y.-C., Wang, S.-H. & Vivone, G. Impact of meteorological conditions and air pollution on COVID-19 pandemic transmission in Italy. _Sci. Rep._ **10**, 16213 (2020).

    [Article](https://doi.org/10.1038%2Fs41598-020-73197-8) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020NatSR..1016183L) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhvF2ksLfE) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Impact%20of%20meteorological%20conditions%20and%20air%20pollution%20on%20COVID-19%20pandemic%20transmission%20in%20Italy&journal=Sci.%20Rep.&doi=10.1038%2Fs41598-020-73197-8&volume=10&publication_year=2020&author=Lolli%2CS&author=Chen%2CY-C&author=Wang%2CS-H&author=Vivone%2CG)

21. Sajadi, M. M. _et al._ Temperature, humidity, and latitude analysis to estimate potential spread and seasonality of coronavirus disease 2019 (COVID-19). _JAMA Netw. Open_ **3**, e2011834 (2020).

    [Article](https://doi.org/10.1001%2Fjamanetworkopen.2020.11834) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Temperature%2C%20humidity%2C%20and%20latitude%20analysis%20to%20estimate%20potential%20spread%20and%20seasonality%20of%20coronavirus%20disease%202019%20%28COVID-19%29&journal=JAMA%20Netw.%20Open&doi=10.1001%2Fjamanetworkopen.2020.11834&volume=3&publication_year=2020&author=Sajadi%2CMM)

22. Marr, L. C., Tang, J. W., Van Mullekom, J. & Lakdawala, S. S. Mechanistic insights into the effect of humidity on airborne influenza virus survival, transmission and incidence. _J. R. Soc. Interface_ **16**, 20180298 (2019).

    [Article](https://doi.org/10.1098%2Frsif.2018.0298) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BC1MXhtFGgsL%2FM) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Mechanistic%20insights%20into%20the%20effect%20of%20humidity%20on%20airborne%20influenza%20virus%20survival%2C%20transmission%20and%20incidence&journal=J.%20R.%20Soc.%20Interface&doi=10.1098%2Frsif.2018.0298&volume=16&publication_year=2019&author=Marr%2CLC&author=Tang%2CJW&author=Mullekom%2CJ&author=Lakdawala%2CSS)

23. Badr, H. S. _et al._ Association between mobility patterns and COVID-19 transmission in the USA: A mathematical modelling study. _Lancet Infect. Dis._ **20**, 1247–1254 (2020).

    [Article](https://doi.org/10.1016%2FS1473-3099%2820%2930553-3) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhtlegtLbK) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Association%20between%20mobility%20patterns%20and%20COVID-19%20transmission%20in%20the%20USA%3A%20A%20mathematical%20modelling%20study&journal=Lancet%20Infect.%20Dis.&doi=10.1016%2FS1473-3099%2820%2930553-3&volume=20&pages=1247-1254&publication_year=2020&author=Badr%2CHS)

24. Gatalo, O., Tseng, K., Hamilton, A., Lin, G. & Klein, E. Associations between phone mobility data and COVID-19 cases. _Lancet Infect. Dis._ **21**, e111 (2020).

    [Article](https://doi.org/10.1016%2FS1473-3099%2820%2930725-8) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Associations%20between%20phone%20mobility%20data%20and%20COVID-19%20cases&journal=Lancet%20Infect.%20Dis.&doi=10.1016%2FS1473-3099%2820%2930725-8&volume=21&publication_year=2020&author=Gatalo%2CO&author=Tseng%2CK&author=Hamilton%2CA&author=Lin%2CG&author=Klein%2CE)

25. Aragão, D. P., dos Santos, D. H., Mondini, A. & Gonçalves, L. M. G. National holidays and social mobility behaviors: Alternatives for forecasting COVID-19 deaths in Brazil. _Int. J. Environ. Res. Public Health_ **18**, 11595 (2021).

    [Article](https://doi.org/10.3390%2Fijerph182111595) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=National%20holidays%20and%20social%20mobility%20behaviors%3A%20Alternatives%20for%20forecasting%20COVID-19%20deaths%20in%20Brazil&journal=Int.%20J.%20Environ.%20Res.%20Public%20Health&doi=10.3390%2Fijerph182111595&volume=18&publication_year=2021&author=Arag%C3%A3o%2CDP&author=Santos%2CDH&author=Mondini%2CA&author=Gon%C3%A7alves%2CLMG)

26. Wang, J. _et al._ High temperature and high humidity reduce the transmission of COVID-19. _SSRN_ [https://doi.org/10.2139/ssrn.3551767](https://doi.org/10.2139/ssrn.3551767) (2020).

    [Article](https://doi.org/10.2139%2Fssrn.3551767) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32742241) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7385481) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=High%20temperature%20and%20high%20humidity%20reduce%20the%20transmission%20of%20COVID-19&journal=SSRN&doi=10.2139%2Fssrn.3551767&publication_year=2020&author=Wang%2CJ)

27. Qi, H. _et al._ COVID-19 transmission in Mainland China is associated with temperature and humidity: A time-series analysis. _Sci. Total Environ._ **728**, 138778 (2020).

    [Article](https://doi.org/10.1016%2Fj.scitotenv.2020.138778) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020ScTEn.728m8778Q) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXotVCqsb0%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=COVID-19%20transmission%20in%20Mainland%20China%20is%20associated%20with%20temperature%20and%20humidity%3A%20A%20time-series%20analysis&journal=Sci.%20Total%20Environ.&doi=10.1016%2Fj.scitotenv.2020.138778&volume=728&publication_year=2020&author=Qi%2CH)

28. Xie, J. & Zhu, Y. Association between ambient temperature and COVID-19 infection in 122 cities from China. _Sci. Total Environ._ **724**, 138201 (2020).

    [Article](https://doi.org/10.1016%2Fj.scitotenv.2020.138201) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020ScTEn.724m8201X) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXmvFKiu7c%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Association%20between%20ambient%20temperature%20and%20COVID-19%20infection%20in%20122%20cities%20from%20China&journal=Sci.%20Total%20Environ.&doi=10.1016%2Fj.scitotenv.2020.138201&volume=724&publication_year=2020&author=Xie%2CJ&author=Zhu%2CY)

29. Poirier, C. _et al._ The role of environmental factors on transmission rates of the COVID-19 outbreak: An initial assessment in two spatial scales. _Sci. Rep._ **10**, 17002 (2020).

    [Article](https://doi.org/10.1038%2Fs41598-020-74089-7) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2020NatSR..1017002P) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXitVOrtbbI) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20role%20of%20environmental%20factors%20on%20transmission%20rates%20of%20the%20COVID-19%20outbreak%3A%20An%20initial%20assessment%20in%20two%20spatial%20scales&journal=Sci.%20Rep.&doi=10.1038%2Fs41598-020-74089-7&volume=10&publication_year=2020&author=Poirier%2CC)

30. Bhagat, R. K., Wykes, M. S. D., Dalziel, S. B. & Linden, P. F. Effects of ventilation on the indoor spread of COVID-19. _J. Fluid Mech._ [https://doi.org/10.1017/jfm.2020.720](https://doi.org/10.1017/jfm.2020.720) (2020).

    [Article](https://doi.org/10.1017%2Fjfm.2020.720) [MathSciNet](http://www.ams.org/mathscinet-getitem?mr=4157431) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=34191877) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC7520710) [MATH](http://www.emis.de/MATH-item?1460.92187) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Effects%20of%20ventilation%20on%20the%20indoor%20spread%20of%20COVID-19&journal=J.%20Fluid%20Mech.&doi=10.1017%2Fjfm.2020.720&publication_year=2020&author=Bhagat%2CRK&author=Wykes%2CMSD&author=Dalziel%2CSB&author=Linden%2CPF)

31. Wickham, H. _ggplot2: Elegant Graphics for Data Analysis_ (Springer-Verlag, 2016).

    [Book](https://link.springer.com/doi/10.1007/978-3-319-24277-4) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=ggplot2%3A%20Elegant%20Graphics%20for%20Data%20Analysis&doi=10.1007%2F978-3-319-24277-4&publication_year=2016&author=Wickham%2CH)

32. Gardner, E. G. _et al._ A case-crossover analysis of the impact of weather on primary cases of Middle East respiratory syndrome. _BMC Infect. Dis._ **19**, 113 (2019).

    [Article](https://link.springer.com/doi/10.1186/s12879-019-3729-5) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=A%20case-crossover%20analysis%20of%20the%20impact%20of%20weather%20on%20primary%20cases%20of%20Middle%20East%20respiratory%20syndrome&journal=BMC%20Infect.%20Dis.&doi=10.1186%2Fs12879-019-3729-5&volume=19&publication_year=2019&author=Gardner%2CEG)

33. Chan, K. H. _et al._ The effects of temperature and relative humidity on the viability of the SARS coronavirus. _Adv. Virol._ **2011**, 1–7 (2011).

    [Article](https://doi.org/10.1155%2F2011%2F734690) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20effects%20of%20temperature%20and%20relative%20humidity%20on%20the%20viability%20of%20the%20SARS%20coronavirus&journal=Adv.%20Virol.&doi=10.1155%2F2011%2F734690&volume=2011&pages=1-7&publication_year=2011&author=Chan%2CKH)

34. Yuan, J. _et al._ A climatologic investigation of the SARS-CoV outbreak in Beijing, China. _Am. J. Infect. Control_ **34**, 234–236 (2006).

    [Article](https://doi.org/10.1016%2Fj.ajic.2005.12.006) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=A%20climatologic%20investigation%20of%20the%20SARS-CoV%20outbreak%20in%20Beijing%2C%20China&journal=Am.%20J.%20Infect.%20Control&doi=10.1016%2Fj.ajic.2005.12.006&volume=34&pages=234-236&publication_year=2006&author=Yuan%2CJ)

35. Altamimi, A. & Ahmed, A. E. Climate factors and incidence of Middle East respiratory syndrome coronavirus. _J. Infect. Public Health_ **13**, 704–708 (2020).

    [Article](https://doi.org/10.1016%2Fj.jiph.2019.11.011) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Climate%20factors%20and%20incidence%20of%20Middle%20East%20respiratory%20syndrome%20coronavirus&journal=J.%20Infect.%20Public%20Health&doi=10.1016%2Fj.jiph.2019.11.011&volume=13&pages=704-708&publication_year=2020&author=Altamimi%2CA&author=Ahmed%2CAE)

36. AntonyAroulRaj, V., Velraj, R. & Haghighat, F. The contribution of dry indoor built environment on the spread of Coronavirus: Data from various Indian states. _Sustain. Cities Soc._ **62**, 102371 (2020).

    [Article](https://doi.org/10.1016%2Fj.scs.2020.102371) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20contribution%20of%20dry%20indoor%20built%20environment%20on%20the%20spread%20of%20Coronavirus%3A%20Data%20from%20various%20Indian%20states&journal=Sustain.%20Cities%20Soc.&doi=10.1016%2Fj.scs.2020.102371&volume=62&publication_year=2020&author=AntonyAroulRaj%2CV&author=Velraj%2CR&author=Haghighat%2CF)

37. McDevitt, J., Rudnick, S., First, M. & Spengler, J. Role of absolute humidity in the inactivation of influenza viruses on stainless steel surfaces at elevated temperatures. _Appl. Environ. Microbiol._ **76**, 3943–3947 (2010).

    [Article](https://doi.org/10.1128%2FAEM.02674-09) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2010ApEnM..76.3943M) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BC3cXptVemsrg%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Role%20of%20absolute%20humidity%20in%20the%20inactivation%20of%20influenza%20viruses%20on%20stainless%20steel%20surfaces%20at%20elevated%20temperatures&journal=Appl.%20Environ.%20Microbiol.&doi=10.1128%2FAEM.02674-09&volume=76&pages=3943-3947&publication_year=2010&author=McDevitt%2CJ&author=Rudnick%2CS&author=First%2CM&author=Spengler%2CJ)

38. Shaman, J., Goldstein, E. & Lipsitch, M. Absolute humidity and pandemic versus epidemic influenza. _Am. J. Epidemiol._ **173**, 127–135 (2011).

    [Article](https://doi.org/10.1093%2Faje%2Fkwq347) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Absolute%20humidity%20and%20pandemic%20versus%20epidemic%20influenza&journal=Am.%20J.%20Epidemiol.&doi=10.1093%2Faje%2Fkwq347&volume=173&pages=127-135&publication_year=2011&author=Shaman%2CJ&author=Goldstein%2CE&author=Lipsitch%2CM)

39. de la Noue, A. C. _et al._ Absolute humidity influences the seasonal persistence and infectivity of human norovirus. _Appl. Environ. Microbiol._ **80**, 7196–7205 (2014).

    [Article](https://doi.org/10.1128%2FAEM.01871-14) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=2014ApEnM..80.7196C) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Absolute%20humidity%20influences%20the%20seasonal%20persistence%20and%20infectivity%20of%20human%20norovirus&journal=Appl.%20Environ.%20Microbiol.&doi=10.1128%2FAEM.01871-14&volume=80&pages=7196-7205&publication_year=2014&author=Noue%2CAC)

40. Ahlawat, A., Wiedensohler, A. & Mishra, S. K. An overview on the role of relative humidity in airborne transmission of SARS-CoV-2 in indoor environments. _Aerosol Air Qual. Res._ **20**, 1856–1861 (2020).

    [Article](https://doi.org/10.4209%2Faaqr.2020.06.0302) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXitFeqtbnE) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=An%20overview%20on%20the%20role%20of%20relative%20humidity%20in%20airborne%20transmission%20of%20SARS-CoV-2%20in%20indoor%20environments&journal=Aerosol%20Air%20Qual.%20Res.&doi=10.4209%2Faaqr.2020.06.0302&volume=20&pages=1856-1861&publication_year=2020&author=Ahlawat%2CA&author=Wiedensohler%2CA&author=Mishra%2CSK)

41. Qiu, H. _et al._ Clinical and epidemiological features of 36 children with coronavirus disease 2019 (COVID-19) in Zhejiang, China: An observational cohort study. _Lancet Infect. Dis_ **20**, 689–696 (2020).

    [Article](https://doi.org/10.1016%2FS1473-3099%2820%2930198-5) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXlsl2gsbw%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Clinical%20and%20epidemiological%20features%20of%2036%20children%20with%20coronavirus%20disease%202019%20%28COVID-19%29%20in%20Zhejiang%2C%20China%3A%20An%20observational%20cohort%20study&journal=Lancet%20Infect.%20Dis&doi=10.1016%2FS1473-3099%2820%2930198-5&volume=20&pages=689-696&publication_year=2020&author=Qiu%2CH)

42. Kelvin, A. A. & Halperin, S. COVID-19 in children: The link in the transmission chain. _Lancet Infect. Dis_ **20**, 633–634 (2020).

    [Article](https://doi.org/10.1016%2FS1473-3099%2820%2930236-X) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXlsl2gsb8%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=COVID-19%20in%20children%3A%20The%20link%20in%20the%20transmission%20chain&journal=Lancet%20Infect.%20Dis&doi=10.1016%2FS1473-3099%2820%2930236-X&volume=20&pages=633-634&publication_year=2020&author=Kelvin%2CAA&author=Halperin%2CS)

43. Viner, R. M. _et al._ School closure and management practices during coronavirus outbreaks including COVID-19: A rapid systematic review. _Lancet Child Adolesc. Health_ **4**, 397–404 (2020).

    [Article](https://doi.org/10.1016%2FS2352-4642%2820%2930095-X) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhtVelsLrF) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=School%20closure%20and%20management%20practices%20during%20coronavirus%20outbreaks%20including%20COVID-19%3A%20A%20rapid%20systematic%20review&journal=Lancet%20Child%20Adolesc.%20Health&doi=10.1016%2FS2352-4642%2820%2930095-X&volume=4&pages=397-404&publication_year=2020&author=Viner%2CRM)

44. Salas, R. N., Shultz, J. M. & Solomon, C. G. The climate crisis and Covid-19—A major threat to the pandemic response. _N. Engl. J. Med._ **383**, e70 (2020).

    [Article](https://doi.org/10.1056%2FNEJMp2022011) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3cXhvVejurrI) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20climate%20crisis%20and%20Covid-19%E2%80%94A%20major%20threat%20to%20the%20pandemic%20response&journal=N.%20Engl.%20J.%20Med.&doi=10.1056%2FNEJMp2022011&volume=383&publication_year=2020&author=Salas%2CRN&author=Shultz%2CJM&author=Solomon%2CCG)

45. Kronfeld-Schor, N. _et al._ Drivers of infectious disease seasonality: Potential implications for COVID-19. _J. Biol. Rhythms_ **36**, 35–54 (2021).

    [Article](https://doi.org/10.1177%2F0748730420987322) [CAS](https://www.nature.com/articles/cas-redirect/1:CAS:528:DC%2BB3MXpslamu74%3D) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Drivers%20of%20infectious%20disease%20seasonality%3A%20Potential%20implications%20for%20COVID-19&journal=J.%20Biol.%20Rhythms&doi=10.1177%2F0748730420987322&volume=36&pages=35-54&publication_year=2021&author=Kronfeld-Schor%2CN)

46. Berndt, D. J. & Clifford, J. Using dynamic time warping to find patterns in time series. 12.

47. Giorgino, T. Computing and visualizing dynamic time warping alignments in R : The dtw package. _J. Stat. Softw._ [https://doi.org/10.18637/jss.v031.i07](https://doi.org/10.18637/jss.v031.i07) (2009).

    [Article](https://doi.org/10.18637%2Fjss.v031.i07) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Computing%20and%20visualizing%20dynamic%20time%20warping%20alignments%20in%20R%20%3A%20The%20dtw%20package&journal=J.%20Stat.%20Softw.&doi=10.18637%2Fjss.v031.i07&publication_year=2009&author=Giorgino%2CT)

48. Silverman, J. D., Hupert, N. & Washburne, A. D. Using influenza surveillance networks to estimate state-specific prevalence of SARS-CoV-2 in the United States. _Sci. Transl. Med._ [https://doi.org/10.1126/scitranslmed.abc1126](https://doi.org/10.1126/scitranslmed.abc1126) (2020).

    [Article](https://doi.org/10.1126%2Fscitranslmed.abc1126) [PubMed](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=32908007) [PubMed Central](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC8571514) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Using%20influenza%20surveillance%20networks%20to%20estimate%20state-specific%20prevalence%20of%20SARS-CoV-2%20in%20the%20United%20States&journal=Sci.%20Transl.%20Med.&doi=10.1126%2Fscitranslmed.abc1126&publication_year=2020&author=Silverman%2CJD&author=Hupert%2CN&author=Washburne%2CAD)

49. 2018 ACS 1-year Estimates. _The United States Census Bureau_ [https://www.census.gov/programs-surveys/acs/technical-documentation/table-and-geography-changes/2018/1-year.html](https://www.census.gov/programs-surveys/acs/technical-documentation/table-and-geography-changes/2018/1-year.html).

50. National Centers for Environmental Information (NCEI). [https://www.ncei.noaa.gov/](https://www.ncei.noaa.gov/).

51. Global Surface Summary of the Day—GSOD—NOAA Data Catalog. [https://data.noaa.gov/dataset/dataset/global-surface-summary-of-the-day-gsod](https://data.noaa.gov/dataset/dataset/global-surface-summary-of-the-day-gsod).

52. Census Block Conversions API. _Federal Communications Commission_ [https://www.fcc.gov/census-block-conversions-api](https://www.fcc.gov/census-block-conversions-api) (2011).

53. Alduchov, O. A. & Eskridge, R. E. Improved Magnus form approximation of saturation vapor pressure. _J. Appl. Meteorol._ **35**, 601–609 (1996).

    [Article](https://doi.org/10.1175%2F1520-0450%281996%29035%3C0601%3AIMFAOS%3E2.0.CO%3B2) [ADS](http://adsabs.harvard.edu/cgi-bin/nph-data_query?link_type=ABSTRACT&bibcode=1996JApMe..35..601A) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=Improved%20Magnus%20form%20approximation%20of%20saturation%20vapor%20pressure&journal=J.%20Appl.%20Meteorol.&doi=10.1175%2F1520-0450%281996%29035%3C0601%3AIMFAOS%3E2.0.CO%3B2&volume=35&pages=601-609&publication_year=1996&author=Alduchov%2COA&author=Eskridge%2CRE)

54. Google LLC. COVID-19 Community Mobility Report. _COVID-19 Community Mobility Report_ [https://www.google.com/covid19/mobility?hl=en](https://www.google.com/covid19/mobility?hl=en).

55. Lauer, S. A. _et al._ The incubation period of coronavirus disease 2019 (COVID-19) from publicly reported confirmed cases: Estimation and application. _Ann. Intern. Med._ **172**, 577–582 (2020).

    [Article](https://doi.org/10.7326%2FM20-0504) [Google Scholar](http://scholar.google.com/scholar_lookup?&title=The%20incubation%20period%20of%20coronavirus%20disease%202019%20%28COVID-19%29%20from%20publicly%20reported%20confirmed%20cases%3A%20Estimation%20and%20application&journal=Ann.%20Intern.%20Med.&doi=10.7326%2FM20-0504&volume=172&pages=577-582&publication_year=2020&author=Lauer%2CSA)


[Download references](https://citation-needed.springer.com/v2/references/10.1038/s41598-022-19898-8?format=refman&flavour=references)

## Acknowledgements

This work was funded by the Centers for Disease Control and Prevention (CDC) MInD-Healthcare Program (Grant Numbers U01CK000589, 1U01CK000536, and contract number 75D30120P07912). The funders had no role in the design, data collection and analysis, decision to publish, or preparation of the manuscript.

## Author information

### Authors and Affiliations

1. Center for Disease Dynamics, Economics & Policy, 962 Wayne Avenue, Suite 530, Silver Spring, MD, 20910-4433, USA

Gary Lin, Alisa Hamilton, Oliver Gatalo, Fardad Haghpanah & Eili Klein

2. Department of Civil and Systems Engineering, Johns Hopkins University, Baltimore, MD, USA

Takeru Igusa

3. Department of Earth and Planetary Sciences, Johns Hopkins University, Baltimore, MD, USA

Takeru Igusa

4. Center for Systems Science and Engineering, Johns Hopkins University, Baltimore, MD, USA

Takeru Igusa

5. Department of Emergency Medicine, Johns Hopkins University, Baltimore, MD, USA

Eili Klein

6. Department of Epidemiology, Johns Hopkins University, Baltimore, MD, USA

Eili Klein


Authors

1. Gary Lin


[View author publications](https://www.nature.com/search?author=Gary%20Lin)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Gary%20Lin) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Gary%20Lin%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

2. Alisa Hamilton


[View author publications](https://www.nature.com/search?author=Alisa%20Hamilton)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Alisa%20Hamilton) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Alisa%20Hamilton%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

3. Oliver Gatalo


[View author publications](https://www.nature.com/search?author=Oliver%20Gatalo)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Oliver%20Gatalo) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Oliver%20Gatalo%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

4. Fardad Haghpanah


[View author publications](https://www.nature.com/search?author=Fardad%20Haghpanah)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Fardad%20Haghpanah) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Fardad%20Haghpanah%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

5. Takeru Igusa


[View author publications](https://www.nature.com/search?author=Takeru%20Igusa)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Takeru%20Igusa) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Takeru%20Igusa%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)

6. Eili Klein


[View author publications](https://www.nature.com/search?author=Eili%20Klein)





Search author on:[PubMed](https://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=search&term=Eili%20Klein) [Google Scholar](https://scholar.google.co.uk/scholar?as_q=&num=10&btnG=Search+Scholar&as_epq=&as_oq=&as_eq=&as_occt=any&as_sauthors=%22Eili%20Klein%22&as_publication=&as_ylo=&as_yhi=&as_allsubj=all&hl=en)


### Contributions

E.K. conceived the research, G.L. designed the study, A.H. and O.G. collected and processed the data, G.L., E.K., F.H., T.I. analyzed and interpreted the data. All authors contributed to interpretation of results and manuscript writing.

### Corresponding author

Correspondence to
[Gary Lin](mailto:lin@CDDEP.org).

## Ethics declarations

### Competing interests

The authors declare no competing interests.

## Additional information

### Publisher's note

Springer Nature remains neutral with regard to jurisdictional claims in published maps and institutional affiliations.

## Supplementary Information

### [Supplementary Information. (download DOCX )](https://static-content.springer.com/esm/art%3A10.1038%2Fs41598-022-19898-8/MediaObjects/41598_2022_19898_MOESM1_ESM.docx)

## Rights and permissions

**Open Access** This article is licensed under a Creative Commons Attribution 4.0 International License, which permits use, sharing, adaptation, distribution and reproduction in any medium or format, as long as you give appropriate credit to the original author(s) and the source, provide a link to the Creative Commons licence, and indicate if changes were made. The images or other third party material in this article are included in the article's Creative Commons licence, unless indicated otherwise in a credit line to the material. If material is not included in the article's Creative Commons licence and your intended use is not permitted by statutory regulation or exceeds the permitted use, you will need to obtain permission directly from the copyright holder. To view a copy of this licence, visit [http://creativecommons.org/licenses/by/4.0/](http://creativecommons.org/licenses/by/4.0/).

[Reprints and permissions](https://s100.copyright.com/AppDispatchServlet?title=Investigating%20the%20effects%20of%20absolute%20humidity%20and%20movement%20on%20COVID-19%20seasonality%20in%20the%20United%20States&author=Gary%20Lin%20et%20al&contentID=10.1038%2Fs41598-022-19898-8&copyright=The%20Author%28s%29&publication=2045-2322&publicationDate=2022-10-06&publisherName=SpringerNature&orderBeanReset=true&oa=CC%20BY)

## About this article

[![Check for updates. Verify currency and authenticity via CrossMark](<Base64-Image-Removed>)](https://crossmark.crossref.org/dialog/?doi=10.1038/s41598-022-19898-8)

### Cite this article

Lin, G., Hamilton, A., Gatalo, O. _et al._ Investigating the effects of absolute humidity and movement on COVID-19 seasonality in the United States.
_Sci Rep_ **12**, 16729 (2022). https://doi.org/10.1038/s41598-022-19898-8

[Download citation](https://citation-needed.springer.com/v2/references/10.1038/s41598-022-19898-8?format=refman&flavour=citation)

- Received: 05 October 2021

- Accepted: 06 September 2022

- Published: 06 October 2022

- Version of record: 06 October 2022

- DOI: https://doi.org/10.1038/s41598-022-19898-8


### Share this article

Anyone you share the following link with will be able to read this content:

Get shareable link

Sorry, a shareable link is not currently available for this article.

Copy shareable link to clipboard

Provided by the Springer Nature SharedIt content-sharing initiative


### Subjects

- [Epidemiology](https://www.nature.com/subjects/epidemiology)
- [Infectious diseases](https://www.nature.com/subjects/infectious-diseases)

Close bannerClose

![Nature Briefing](https://www.nature.com/static/images/logos/nature-briefing-logo-n150-white-afc2e6ccc7.svg)

Sign up for the _Nature Briefing_ newsletter — what matters in science, free to your inbox daily.

Email address

Sign up

I agree my information will be processed in accordance with the _Nature_ and Springer Nature Limited [Privacy Policy](https://www.nature.com/info/privacy).

Close bannerClose

Get the most important science stories of the day, free in your inbox. [Sign up for Nature Briefing](https://www.nature.com/briefing/signup/?brieferEntryPoint=MainBriefingBanner)