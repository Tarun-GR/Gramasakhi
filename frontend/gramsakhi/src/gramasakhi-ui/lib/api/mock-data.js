export const VERIFIED_SCHEMES = [
  {
    id: 'pm-kisan',
    name: 'PM-KISAN Samman Nidhi',
    shortDescription: 'Provides income support of ₹6,000 per year in three equal installments to all landholding farmer families.',
    category: 'agriculture',
    categoryLabel: 'Agriculture & DBT',
    department: 'Ministry of Agriculture & Farmers Welfare',
    fundingType: 'Central',
    maxBenefitAmount: '₹6,000 / year',
    benefits: [
      'Direct income support of ₹6,000 per year transferred directly to bank account.',
      'Paid in three equal installments of ₹2,000 every four months (April-July, Aug-Nov, Dec-March).',
      'Zero intermediaries with direct DBT transfer to Aadhaar-seeded accounts.',
      'Applicable in addition to state-level agricultural input subsidies.'
    ],
    eligibility: [
      'All landholder farmer families having cultivable landholding in their names.',
      'Must have valid Aadhaar card and active Aadhaar-linked bank account with NPCI mapping.',
      'Institutional landholders and high-income tax payers are excluded.'
    ],
    documentsRequired: [
      'Aadhaar Card of the applicant',
      'Land Ownership Record (RTC / Pahani / 7/12 extract / Khasra)',
      'Bank Account Passbook / Statement linked with Aadhaar',
      'Mobile number linked with Aadhaar OTP'
    ],
    applicationMethod: 'Online via pmkisan.gov.in portal, through CSC / Grama One centers, or Village Agriculture Officer.',
    officialPortalUrl: 'https://pmkisan.gov.in'
  },
  {
    id: 'pm-awas-gramin',
    name: 'Pradhan Mantri Awas Yojana - Gramin (PMAY-G)',
    shortDescription: 'Financial assistance for construction of pucca houses with basic amenities for rural homeless and kutcha house residents.',
    category: 'housing',
    categoryLabel: 'Housing & Shelter',
    department: 'Ministry of Rural Development',
    fundingType: 'Centrally Sponsored',
    maxBenefitAmount: '₹1,20,000 to ₹1,30,000',
    benefits: [
      'Grant of ₹1,20,000 in plain areas and ₹1,30,000 in hilly/difficult areas for house construction.',
      'Additional 90/95 person-days of unskilled labor support under MGNREGS (approx. ₹27,000).',
      'Assistance of ₹12,000 for toilet construction through Swachh Bharat Mission (Grameen).',
      'LPG connection through PM Ujjwala Yojana and electricity connection through Saubhagya.'
    ],
    eligibility: [
      'Families living in kutcha/dilapidated houses or houseless households based on SECC 2011 data / Awas+ list.',
      'No adult earning member between 16 and 59 years or female-headed households with no adult male member.',
      'Must not own a motorized vehicle, mechanized farm equipment, or kisan credit card with limit ≥ ₹50,000.'
    ],
    documentsRequired: [
      'Aadhaar Card of all family members',
      'MGNREGA Job Card Number',
      'Bank Account details (Aadhaar linked)',
      'Consent form for Aadhaar authentication',
      'Photographs of current kutcha house / site'
    ],
    applicationMethod: 'Identified via Gram Sabha and registered by Gram Panchayat Secretary / Block Development Officer.',
    officialPortalUrl: 'https://pmayg.nic.in'
  },
  {
    id: 'gruha-lakshmi-ka',
    name: 'Karnataka Gruha Lakshmi Scheme',
    shortDescription: 'Monthly financial assistance of ₹2,000 for women head of households in Karnataka.',
    category: 'women',
    categoryLabel: 'Women & Child Welfare',
    department: 'Department of Women & Child Development, Govt of Karnataka',
    fundingType: 'State',
    state: 'Karnataka',
    maxBenefitAmount: '₹2,000 / month',
    benefits: [
      'Monthly direct bank transfer of ₹2,000 to the woman head of the family.',
      'Unconditional financial autonomy to support household nutrition and children education.',
      'Automatic integration with DBT Karnataka citizen wallet.'
    ],
    eligibility: [
      'Female head of household indicated on Antyodaya (AAY), BPL, or APL ration cards.',
      'Neither the applicant woman nor her husband should be income tax payers or GST filers.',
      'Only one woman per household is eligible.'
    ],
    documentsRequired: [
      'Ration Card (APL / BPL / Antyodaya)',
      'Aadhaar Card of applicant and spouse',
      'Aadhaar-linked Bank Account (with NPCI mapping)',
      'Aadhaar linked active Mobile number'
    ],
    applicationMethod: 'Online via Seva Sindhu / Karnataka One / Grama One centers or designated Bapuji Seva Kendras.',
    officialPortalUrl: 'https://sevasindhu.karnataka.gov.in'
  },
  {
    id: 'ayushman-bharat-pmjay',
    name: 'Ayushman Bharat PM-JAY (Arogya Karnataka)',
    shortDescription: 'Health insurance coverage of up to ₹5 Lakh per family per year for secondary and tertiary hospitalization care.',
    category: 'health',
    categoryLabel: 'Health & Ayushman',
    department: 'National Health Authority (NHA) & Suvarna Arogya Suraksha Trust',
    fundingType: 'Centrally Sponsored',
    maxBenefitAmount: '₹5,00,000 / year',
    benefits: [
      'Cashless and paperless access to healthcare services up to ₹5,00,000 per family per year.',
      'Covers over 1,900 medical and surgical treatment procedures including surgery, oncology, cardiology, etc.',
      'No cap on family size or age of members; pre-existing conditions covered from day one.',
      'Valid across all empaneled public and private hospitals across India.'
    ],
    eligibility: [
      'Households listed in SECC 2011 rural and urban deprivation criteria / NFSA Ration Card holders.',
      'All BPL / AAY ration card holder families in Karnataka (co-branded as AB-ArK).',
      'Citizens aged 70 and above eligible for dedicated Ayushman Vaya Vandana card regardless of income.'
    ],
    documentsRequired: [
      'Aadhaar Card',
      'Valid Ration Card (BPL/Antyodaya)',
      'Active Mobile number for e-KYC'
    ],
    applicationMethod: 'Generate Ayushman Card at nearest Grama One center, Common Service Center (CSC), or District Hospital Arogya Mitra counter.',
    officialPortalUrl: 'https://beneficiary.nha.gov.in'
  },
  {
    id: 'pm-krishi-sinchayee',
    name: 'PM Krishi Sinchayee Yojana (Micro Irrigation)',
    shortDescription: 'Up to 90% subsidy for drip and sprinkler irrigation systems for small and marginal farmers in Karnataka.',
    category: 'agriculture',
    categoryLabel: 'Agriculture & Water',
    department: 'Department of Agriculture & Horticulture, Govt of Karnataka',
    fundingType: 'Centrally Sponsored',
    maxBenefitAmount: 'Up to 90% subsidy',
    benefits: [
      '90% subsidy for SC/ST and small/marginal farmers (up to 5 acres) for installing drip/sprinkler units.',
      'Saves 40% to 60% water while increasing crop yield by 20% to 30%.',
      'Direct inspection and installation by empaneled micro-irrigation equipment manufacturers.'
    ],
    eligibility: [
      'Farmers holding agricultural land with assured irrigation water source (borewell, open well, canal).',
      'Valid land record (RTC) in the name of the farmer.',
      'Has not availed micro-irrigation subsidy for the same survey number in the last 7 years.'
    ],
    documentsRequired: [
      'RTC / Pahani (Latest 3 months)',
      'Aadhaar Card & Photo',
      'Bank Passbook photocopy',
      'Water & Electricity source certificate / borewell yield report',
      'Caste & Income Certificate (for SC/ST subsidy)'
    ],
    applicationMethod: 'Apply online through Raitha Siri / Fruits Karnataka portal or visit the Raitha Samparka Kendra (RSK).',
    officialPortalUrl: 'https://fruits.karnataka.gov.in'
  }
];

export const MOCK_EVIDENCE_SOURCES = {
  'pm-kisan': [
    {
      id: 'src-pmk-1',
      title: 'PM-KISAN Scheme Operational Guidelines',
      department: 'Ministry of Agriculture and Farmers Welfare, Govt of India',
      documentType: 'Official Scheme Manual',
      excerpt: 'Under the scheme, financial assistance of Rs. 6,000/- per annum is provided to all landholding farmer families across the country, subject to certain exclusions. The amount is paid in three equal 4-monthly installments.',
      url: 'https://pmkisan.gov.in',
      isOfficial: true,
      schemeId: 'pm-kisan'
    },
    {
      id: 'src-pmk-2',
      title: 'FRUITS Karnataka DBT Portal Integration Notice',
      department: 'Department of Agriculture, Govt of Karnataka',
      documentType: 'State Government Circular',
      excerpt: 'Karnataka farmers registered on FRUITS (Farmer Registration and Unified Beneficiary Information System) receive seamless PM-KISAN matching and state additional incentive transfers directly to NPCI-mapped accounts.',
      url: 'https://fruits.karnataka.gov.in',
      isOfficial: true,
      schemeId: 'pm-kisan'
    }
  ],
  'pm-awas-gramin': [
    {
      id: 'src-pmay-1',
      title: 'PMAY-G Framework for Implementation',
      department: 'Ministry of Rural Development, Govt of India',
      documentType: 'Official Guidelines',
      excerpt: 'Unit assistance of Rs. 1.20 lakh in plain areas and Rs. 1.30 lakh in hilly states is provided to rural households living in kutcha houses as identified by the SECC 2011 and Awas+ list.',
      url: 'https://pmayg.nic.in',
      isOfficial: true,
      schemeId: 'pm-awas-gramin'
    }
  ],
  'gruha-lakshmi-ka': [
    {
      id: 'src-gl-1',
      title: 'Gruha Lakshmi Scheme Government Order (DWCD 123)',
      department: 'Department of Women & Child Development, Govt of Karnataka',
      documentType: 'Government Order (G.O.)',
      excerpt: 'The Government of Karnataka provides Rs. 2,000 per month financial empowerment assistance to the woman designated as family head on BPL, Antyodaya and APL ration cards via direct bank transfer.',
      url: 'https://sevasindhu.karnataka.gov.in',
      isOfficial: true,
      schemeId: 'gruha-lakshmi-ka'
    }
  ],
  'ayushman-bharat-pmjay': [
    {
      id: 'src-ab-1',
      title: 'National Health Authority Beneficiary Guidelines',
      department: 'National Health Authority (NHA)',
      documentType: 'Official Health Scheme Guidelines',
      excerpt: 'PM-JAY provides health cover of Rs. 5 lakh per family per year for secondary and tertiary care hospitalization to over 12 crore poor and vulnerable families.',
      url: 'https://beneficiary.nha.gov.in',
      isOfficial: true,
      schemeId: 'ayushman-bharat-pmjay'
    }
  ]
};
