// Labeled eval set for the sorting step (recruiter outreach or not, and
// which category). Every email here is synthetic - no real inbox content -
// written to cover the common cases plus the traps the classifier prompt
// calls out: healthcare admin tooling vs patient-outcome AI, vendor pitches
// that use hiring words, job-board digests, excluded companies, and emails
// too vague to tell. Labels were written before either sorter was run.
//
// gold.category: 'ignore' | 'keep_warm' | 'high_interest'. Non-outreach is
// always 'ignore'. `ambiguous: true` marks cases where a careful human could
// reasonably pick a different category; they're reported separately.

export const PREFERENCES = {
  target_areas:
    'Healthcare AI focused on patient outcomes (not admin/scheduling tooling), ' +
    'climate tech, venture studios',
  seniority: 'Staff, Principal, or Head of Engineering',
  comp_floor: 250000,
  company_excludes: 'Initech, Globex',
}

const out = (category, extra = {}) => ({ gold: { is_recruiter_outreach: true, category }, ...extra })
const notOutreach = (extra = {}) => ({
  gold: { is_recruiter_outreach: false, category: 'ignore' },
  ...extra,
})

export const CASES = [
  // --- Not recruiter outreach -------------------------------------------
  {
    id: 'nl-hiring-trends',
    sender: 'The Pragmatic Engineer <newsletter@pragmaticengineer.com>',
    subject: 'The state of tech hiring in Q3',
    body: 'This week: why hiring for staff roles slowed, what recruiters are seeing, and how interview loops are changing. Plus: a deep dive into on-call. Unsubscribe anytime.',
    ...notOutreach({ tags: ['newsletter', 'hiring-words'] }),
  },
  {
    id: 'linkedin-job-alert',
    sender: 'LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>',
    subject: '30+ new jobs for "Staff Engineer" in New York',
    body: 'Staff Software Engineer - Stripe. Principal Engineer - Datadog. Staff Engineer, Platform - Ramp. See all jobs. You are receiving job alert emails.',
    ...notOutreach({ tags: ['job-board-digest'] }),
  },
  {
    id: 'indeed-digest',
    sender: 'Indeed <alert@indeed.com>',
    subject: 'Senior Engineer opportunities near you',
    body: 'Based on your recent searches, here are 12 new positions. Apply with your Indeed resume in one click.',
    ...notOutreach({ tags: ['job-board-digest', 'hiring-words'] }),
  },
  {
    id: 'colleague-interview-loop',
    sender: 'Priya Shah <priya@currentco.com>',
    subject: 'Interview loop for the backend candidate tomorrow',
    body: "Hey Edison, can you take the system design round for the backend candidate at 2pm tomorrow? Recruiting sent the packet. I'll do the coding round.",
    ...notOutreach({ tags: ['colleague', 'hiring-words'] }),
  },
  {
    id: 'vendor-recruiting-tool',
    sender: 'Mark from HireFlow <mark@hireflow.io>',
    subject: 'Hiring engineers faster at CurrentCo?',
    body: "Hi Edison, I saw CurrentCo has 14 open engineering roles. HireFlow helps engineering leaders cut time-to-hire by 40% with AI sourcing. Worth a 15 minute demo next week?",
    ...notOutreach({ tags: ['vendor-pitch', 'hiring-words'] }),
  },
  {
    id: 'friend-referral-ask',
    sender: 'Dan Lee <dan.lee@gmail.com>',
    subject: 'quick favor - referral?',
    body: "Hey man, I'm applying to the platform role at your company. Any chance you could refer me? Resume attached. Beers on me next week either way.",
    ...notOutreach({ tags: ['personal', 'hiring-words'] }),
  },
  {
    id: 'receipt',
    sender: 'Uber Receipts <noreply@uber.com>',
    subject: 'Your Thursday evening trip with Uber',
    body: 'Thanks for riding, Edison. Total $23.40. Rate your driver.',
    ...notOutreach({ tags: ['transactional'] }),
  },
  {
    id: 'conference-invite',
    sender: 'ClimateTech Summit <events@climatetechsummit.com>',
    subject: 'Speaker opportunity: ClimateTech Summit 2027',
    body: "We're inviting engineering leaders to speak at ClimateTech Summit in March. Submit a talk proposal by Nov 1. Early-bird tickets available now.",
    ...notOutreach({ tags: ['event', 'target-area-words'] }),
  },
  {
    id: 'mom',
    sender: 'Mom <linda.moy@gmail.com>',
    subject: 'thanksgiving',
    body: 'Are you coming home for thanksgiving? Your aunt wants to know about your new position at work. Call me.',
    ...notOutreach({ tags: ['personal', 'hiring-words'] }),
  },
  {
    id: 'spam-crypto',
    sender: 'Opportunity Desk <win@cryptoyield-now.biz>',
    subject: 'Exclusive opportunity: 40% monthly returns',
    body: 'Dear investor, this is a limited opportunity to join our trading position pool. Reply now to secure your spot.',
    ...notOutreach({ tags: ['spam', 'hiring-words'] }),
  },
  {
    id: 'candidate-applying',
    sender: 'Alex Rivera <alex.rivera.dev@gmail.com>',
    subject: 'Application: Senior Backend Engineer role',
    body: 'Hi Edison, I saw your post about the Senior Backend role on your team and wanted to reach out directly. I have 6 years of Go experience. Would love to interview.',
    ...notOutreach({ tags: ['inbound-candidate', 'hiring-words'] }),
  },
  {
    id: 'saas-renewal',
    sender: 'Greenhouse <billing@greenhouse.io>',
    subject: 'Your Greenhouse Recruiting subscription renews in 30 days',
    body: 'Your talent acquisition plan renews on Oct 28. No action needed. Manage your plan in settings.',
    ...notOutreach({ tags: ['transactional', 'hiring-words'] }),
  },
  {
    id: 'alumni-newsletter',
    sender: 'Cornell Alumni <alumni@cornell.edu>',
    subject: 'Alumni spotlight + career fair',
    body: 'Read about alumni building in climate and health. Join our virtual career fair on Oct 15 where employers are hiring for many roles.',
    ...notOutreach({ tags: ['newsletter', 'target-area-words'] }),
  },
  {
    id: 'investor-update',
    sender: 'Jordan at Lowercarbon <jordan@lowercarbon.example>',
    subject: 'Q3 portfolio update',
    body: 'Hi LPs and friends, this quarter our portfolio companies raised $400M. Highlights: grid storage, direct air capture, and methane detection. Full memo attached.',
    ...notOutreach({ tags: ['newsletter', 'target-area-words'] }),
  },

  // --- Ordinary recruiter outreach: keep_warm ----------------------------
  {
    id: 'kw-fintech-generic',
    sender: 'Pat Kim <pat@talentbridge.com>',
    subject: 'Exciting opportunity',
    body: 'Hi Edison, I have a Staff Backend Engineer role at a Series C payments fintech. $270-300k base plus equity, NYC hybrid. Open to a quick call this week?',
    ...out('keep_warm', { tags: ['fintech'] }),
  },
  {
    id: 'kw-bigtech',
    sender: 'Sarah Chen <sarahchen@google.com>',
    subject: 'Staff SWE roles at Google',
    body: "Hi Edison, I'm a technical recruiter at Google. Your background in distributed systems stood out. We're hiring Staff SWEs in Ads infrastructure. Would you be open to a chat?",
    ...out('keep_warm', { tags: ['big-tech'] }),
  },
  {
    id: 'kw-adtech',
    sender: 'Mike Torres <mike@adscale.io>',
    subject: 'Head of Engineering @ AdScale',
    body: "Edison - I'm the CEO of AdScale, a programmatic ad marketplace (Series B, 60 people). We're looking for a Head of Engineering. Comp is $300k + 1% equity. Could we grab coffee?",
    ...out('keep_warm', { tags: ['adtech', 'founder'] }),
  },
  {
    id: 'kw-crypto',
    sender: 'Jess <jess@chainhire.xyz>',
    subject: 'Principal Engineer - DeFi protocol',
    body: 'Hey Edison! A top DeFi protocol is hiring a Principal Engineer, fully remote, $350k + tokens. Let me know if you want details.',
    ...out('keep_warm', { tags: ['crypto'] }),
  },
  {
    id: 'kw-health-scheduling',
    sender: 'Rachel Green <rachel@careschedule.com>',
    subject: 'Staff Engineer - AI for clinic scheduling',
    body: 'Hi Edison, CareSchedule uses AI to optimize appointment scheduling and reduce no-shows for clinic front desks. We are hiring a Staff Engineer to lead our ML platform. $260k + equity, remote.',
    ...out('keep_warm', { tags: ['trap-health-admin'] }),
  },
  {
    id: 'kw-health-billing',
    sender: 'Tom Nguyen <tom@claimwise.ai>',
    subject: 'ClaimWise - Head of Engineering',
    body: 'Edison, ClaimWise automates medical billing and insurance claims with LLMs, cutting denial rates for hospital revenue cycle teams. Looking for a Head of Engineering. Interested?',
    ...out('keep_warm', { tags: ['trap-health-admin'] }),
  },
  {
    id: 'kw-oil-gas',
    sender: 'Brian Walsh <bwalsh@petrosoft.com>',
    subject: 'Energy software - Staff role',
    body: 'Hi Edison, PetroSoft builds drilling optimization software for oil and gas operators. We are an energy company hiring a Staff Engineer in Houston or remote. $280k.',
    ...out('keep_warm', { tags: ['trap-climate-adjacent'] }),
  },
  {
    id: 'kw-ecommerce',
    sender: 'Lauren <lauren@shopstack.com>',
    subject: 'Engineering leadership at ShopStack',
    body: "Hi Edison, ShopStack powers checkout for 20k DTC brands. We're growing the platform org and looking for a Principal Engineer. Would love to tell you more.",
    ...out('keep_warm', { tags: ['ecommerce'] }),
  },
  {
    id: 'kw-agency-vague',
    sender: 'Kevin Patel <kevin@techtalentpartners.com>',
    subject: 'Your profile',
    body: "Hi Edison, came across your profile and was impressed. I'm working on several senior engineering roles with top startups. Do you have 15 minutes to connect?",
    ...out('keep_warm', { tags: ['vague'] }),
  },
  {
    id: 'kw-junior-role',
    sender: 'Amy Lin <amy@devstaff.com>',
    subject: 'Software Engineer II opening',
    body: 'Hi Edison, I have a Software Engineer II role at a logistics startup, $150k. Let me know if you or anyone you know is interested!',
    ...out('keep_warm', { tags: ['below-seniority'], ambiguous: true }),
  },
  {
    id: 'kw-followup',
    sender: 'Pat Kim <pat@talentbridge.com>',
    subject: 'Re: Exciting opportunity',
    body: "Hi Edison, just bumping this in case it got buried. The fintech team is moving quickly on the Staff Backend role. Let me know if you're open to a chat!",
    ...out('keep_warm', { tags: ['fintech', 'follow-up'] }),
  },
  {
    id: 'kw-security',
    sender: 'Nina Park <nina@vaultline.com>',
    subject: 'Staff Engineer - Vaultline (cybersecurity)',
    body: 'Hi Edison, Vaultline is a Series B cloud security company. We are hiring a Staff Engineer for our detection pipeline. $290k + equity, SF or remote.',
    ...out('keep_warm', { tags: ['security'] }),
  },
  {
    id: 'kw-gaming',
    sender: 'Chris <chris@questforge.gg>',
    subject: 'Game backend lead',
    body: "Hey Edison, QuestForge is building a multiplayer game platform. We're looking for a Principal Backend Engineer. Would you be up for a call?",
    ...out('keep_warm', { tags: ['gaming'] }),
  },
  {
    id: 'kw-hr-tech',
    sender: 'Olivia Scott <olivia@peoplegrid.com>',
    subject: 'Head of Eng - HR tech',
    body: 'Hi Edison, PeopleGrid builds payroll and benefits software for mid-market companies. We need a Head of Engineering. $275k base.',
    ...out('keep_warm', { tags: ['hr-tech'] }),
  },
  {
    id: 'kw-health-pharmacy-ops',
    sender: 'Sam Ortiz <sam@rxroute.com>',
    subject: 'RxRoute - Staff Engineer',
    body: 'Hi Edison, RxRoute uses ML to optimize pharmacy inventory and prior-authorization paperwork for pharmacy chains. Hiring a Staff Engineer, $265k, remote.',
    ...out('keep_warm', { tags: ['trap-health-admin'] }),
  },
  {
    id: 'kw-ai-generic',
    sender: 'Maya Brooks <maya@aistaffing.com>',
    subject: 'AI startup - Staff ML Engineer',
    body: "Hi Edison, a well-funded generative AI startup building coding assistants is hiring a Staff ML Engineer. $320k + equity. Interested in learning more?",
    ...out('keep_warm', { tags: ['ai-generic'] }),
  },
  {
    id: 'kw-greenwashing',
    sender: 'Eric Hall <eric@fastfashionhub.com>',
    subject: 'Sustainability-minded engineering leader?',
    body: 'Hi Edison, FastFashionHub is a fast-growing apparel marketplace with a new sustainability page. We are hiring a Head of Engineering to scale our storefront. $280k.',
    ...out('keep_warm', { tags: ['trap-climate-adjacent'] }),
  },
  {
    id: 'kw-real-estate',
    sender: 'Diane Wu <diane@homeloop.com>',
    subject: 'Principal Engineer at HomeLoop',
    body: "Hi Edison, HomeLoop is modernizing home buying with an instant-offer platform. We're hiring a Principal Engineer. Would you like to chat?",
    ...out('keep_warm', { tags: ['proptech'] }),
  },

  // --- Target-area outreach: high_interest -------------------------------
  {
    id: 'hi-carbon-removal',
    sender: 'Sam Lee <sam@carbonco.io>',
    subject: 'Staff Engineer at CarbonCo',
    body: 'Hi Edison, I lead hiring at CarbonCo. We build measurement and verification software for carbon removal projects. Staff Engineer, $280k base, remote. Interested in chatting?',
    ...out('high_interest', { tags: ['climate'] }),
  },
  {
    id: 'hi-grid-storage',
    sender: 'Ana Silva <ana@gridwell.energy>',
    subject: 'Head of Software - grid batteries',
    body: 'Edison, Gridwell deploys and dispatches grid-scale battery storage to help utilities integrate more solar and wind. We are looking for a Head of Software. $300k + equity.',
    ...out('high_interest', { tags: ['climate'] }),
  },
  {
    id: 'hi-sepsis',
    sender: 'Dr. Kim Hart <kim@sepsisguard.ai>',
    subject: 'Principal Engineer - early sepsis detection',
    body: "Hi Edison, I'm the CTO of SepsisGuard. Our models flag sepsis in ICU patients hours earlier, and our hospital pilots cut mortality by 18%. We're hiring a Principal Engineer. $290k + equity.",
    ...out('high_interest', { tags: ['health-outcomes'] }),
  },
  {
    id: 'hi-oncology',
    sender: 'Liam Ford <liam@tumorlens.com>',
    subject: 'TumorLens - Staff Engineer',
    body: 'Hi Edison, TumorLens uses computer vision on pathology slides to help oncologists choose treatments that improve patient survival. Hiring a Staff Engineer to lead inference infra. $275k.',
    ...out('high_interest', { tags: ['health-outcomes'] }),
  },
  {
    id: 'hi-venture-studio',
    sender: 'Megan Price <megan@forgestudio.vc>',
    subject: 'Founding engineer / EIR at Forge Studio',
    body: 'Hi Edison, Forge Studio is a venture studio that spins up 3-4 companies a year. We are looking for a technical Entrepreneur in Residence to co-found our next company. Salary plus founder equity.',
    ...out('high_interest', { tags: ['venture-studio'] }),
  },
  {
    id: 'hi-studio-cto',
    sender: 'Omar Haddad <omar@atomicstudio.co>',
    subject: 'CTO-in-residence role',
    body: "Hey Edison, Atomic is a startup studio. We incubate companies from idea to Series A and we're hiring a CTO-in-residence to lead engineering across our next two builds. $260k + equity in each.",
    ...out('high_interest', { tags: ['venture-studio'] }),
  },
  {
    id: 'hi-ev-charging',
    sender: 'Grace Liu <grace@voltpath.com>',
    subject: 'Staff Engineer - VoltPath',
    body: 'Hi Edison, VoltPath builds the software that runs public EV fast-charging networks and balances load on the grid. Staff Engineer role, $270k, remote.',
    ...out('high_interest', { tags: ['climate'] }),
  },
  {
    id: 'hi-methane',
    sender: 'Ben Carter <ben@methanesat.example>',
    subject: 'Satellite methane detection - engineering lead',
    body: "Edison - we detect methane leaks from orbit and help operators fix them, cutting emissions. We're hiring a Head of Engineering for our data platform. Can we talk?",
    ...out('high_interest', { tags: ['climate'] }),
  },
  {
    id: 'hi-remote-monitoring',
    sender: 'Nora Blake <nora@heartbeat.health>',
    subject: 'Heartbeat Health - Principal Engineer',
    body: "Hi Edison, Heartbeat Health provides AI-driven remote monitoring for heart failure patients, and our program reduced hospital readmissions 30%. We're hiring a Principal Engineer. $285k.",
    ...out('high_interest', { tags: ['health-outcomes'] }),
  },
  {
    id: 'hi-vague-climate',
    sender: 'Jake Moss <jake@terra-talent.com>',
    subject: 'Climate startup - Staff role',
    body: 'Hi Edison, I am working with a seed-stage climate startup decarbonizing cement production. They need a Staff Engineer to build their process-control software. Open to a chat?',
    ...out('high_interest', { tags: ['climate', 'via-agency'] }),
  },
  {
    id: 'hi-mental-health',
    sender: 'Ivy Chen <ivy@mindbridge.health>',
    subject: 'MindBridge - Head of Engineering',
    body: "Hi Edison, MindBridge uses ML to match patients with the right therapist and measures symptom improvement over time; our patients' PHQ-9 scores drop 2x faster. Head of Engineering role, $300k.",
    ...out('high_interest', { tags: ['health-outcomes'] }),
  },
  {
    id: 'hi-drug-discovery',
    sender: 'Paul Grant <paul@molecula.bio>',
    subject: 'Staff ML Infra - Molecula',
    body: 'Hi Edison, Molecula uses AI to design drugs for rare pediatric cancers; two of our candidates are in trials. Hiring a Staff ML Infrastructure Engineer. $280k + equity.',
    ...out('high_interest', { tags: ['health-outcomes'], ambiguous: true }),
  },
  {
    id: 'hi-studio-vague',
    sender: 'Rita Gomez <rita@launchlab.ventures>',
    subject: 'LaunchLab - builder roles',
    body: 'Hi Edison, LaunchLab builds companies from scratch alongside our investors. We have an opening for a senior technical builder to lead product engineering on new ventures. Interested?',
    ...out('high_interest', { tags: ['venture-studio', 'vague'] }),
  },
  {
    id: 'hi-climate-below-floor',
    sender: 'Leo Park <leo@soilsense.ag>',
    subject: 'SoilSense - Staff Engineer',
    body: 'Hi Edison, SoilSense measures soil carbon to pay farmers for regenerative practices. Staff Engineer, $210k + meaningful equity, remote.',
    ...out('high_interest', { tags: ['climate', 'below-comp'], ambiguous: true }),
  },
  {
    id: 'hi-wildfire',
    sender: 'Maria Lopez <maria@firesight.ai>',
    subject: 'FireSight - Principal Engineer',
    body: "Hi Edison, FireSight predicts wildfire spread from satellite and weather data for utilities and fire agencies as the climate warms. We're hiring a Principal Engineer. $275k.",
    ...out('high_interest', { tags: ['climate'] }),
  },

  // --- Harder cases: mixed or misleading signals -------------------------
  {
    id: 'hard-design-studio',
    sender: 'Zoe Adams <zoe@pixelstudio.design>',
    subject: 'Studio role - engineering lead',
    body: "Hi Edison, Pixel Studio is a digital design agency building websites and apps for consumer brands. We're hiring an Engineering Lead to run our client delivery team. $240k.",
    ...out('keep_warm', { tags: ['trap-studio'] }),
  },
  {
    id: 'hard-hospital-marketing',
    sender: 'Greg Stone <greg@carereach.com>',
    subject: 'Improve patient outcomes with CareReach',
    body: "Hi Edison, CareReach is the patient engagement CRM hospitals use to fill appointment slots and run marketing campaigns - better engagement means better outcomes! We're hiring a Staff Engineer. $265k.",
    ...out('keep_warm', { tags: ['trap-health-admin', 'buzzwords'] }),
  },
  {
    id: 'hard-excluded-as-client',
    sender: 'Tara Quinn <tara@apexsearch.com>',
    subject: 'Staff Engineer - logistics',
    body: "Hi Edison, Apex Search has placed engineers at Initech, Globex and Hooli. Today I'm recruiting for FreightOwl, a trucking logistics marketplace, for a Staff Engineer role at $285k. Interested?",
    ...out('keep_warm', { tags: ['trap-excluded-mention'] }),
  },
  {
    id: 'hard-linkedin-inmail',
    sender: 'LinkedIn <inmail-hit-reply@linkedin.com>',
    subject: 'Jordan Blake sent you a new message',
    body: "Jordan Blake, Technical Recruiter at Robinhood: 'Hi Edison, we're growing our brokerage infrastructure team and hiring a Staff Engineer. Would you be open to a chat?' Reply on LinkedIn.",
    ...out('keep_warm', { tags: ['notification-wrapper', 'fintech'] }),
  },
  {
    id: 'hard-friend-founder-climate',
    sender: 'Marcus <marcus.w@gmail.com>',
    subject: 'crazy idea',
    body: "Yo Edison! So we just closed our seed for the heat-pump installer software company I told you about at the wedding. Would you ever consider joining as Head of Eng? Can't pay Google money but real equity. No pressure, let's grab a beer.",
    ...out('high_interest', { tags: ['personal-tone', 'climate'] }),
  },
  {
    id: 'hard-fusion',
    sender: 'Helen Voss <helen@brightstar-fusion.com>',
    subject: 'Controls software - Principal Engineer',
    body: 'Hi Edison, BrightStar is building a compact fusion reactor to deliver carbon-free baseload power. We need a Principal Engineer for our plasma control software. $300k + equity.',
    ...out('high_interest', { tags: ['climate'] }),
  },
  {
    id: 'hard-carbon-marketplace',
    sender: 'Ravi Menon <ravi@offsetx.com>',
    subject: 'OffsetX - Staff Engineer',
    body: 'Hi Edison, OffsetX runs a marketplace for verified carbon credits so companies can fund forestry and direct-air-capture projects. Hiring a Staff Engineer for our registry platform. $270k.',
    ...out('high_interest', { tags: ['climate', 'fintech-adjacent'] }),
  },
  {
    id: 'hard-ambient-scribe',
    sender: 'Elena Cruz <elena@notewell.ai>',
    subject: 'NoteWell - Head of Engineering',
    body: 'Hi Edison, NoteWell is an ambient AI scribe that writes clinical notes during visits so doctors spend less time on paperwork. Head of Engineering, $310k + equity.',
    ...out('keep_warm', { tags: ['trap-health-admin'], ambiguous: true }),
  },
  {
    id: 'hard-buried-lede',
    sender: 'Recruiting Team <careers@talentwave.com>',
    subject: 'Following up',
    body: 'Hello! Hope your week is going well. TalentWave partners with hundreds of companies across every industry, from startups to Fortune 500s, and we pride ourselves on candidate experience and white-glove service at every step of the process. We are always happy to answer questions about the market. Anyway - one of our clients, a Series A startup using machine learning to predict and prevent diabetic foot ulcers and amputations, is looking for a Staff Engineer at $260k. Let us know!',
    ...out('high_interest', { tags: ['health-outcomes', 'buried'] }),
  },
  {
    id: 'hard-recruiter-newsletter',
    sender: 'Kelly at TechRecruit <kelly@techrecruit.com>',
    subject: 'Hot jobs this week',
    body: "Hi there! This week's hot jobs: Staff Engineer at a climate startup, Principal at a healthtech, and more. Reply to this newsletter if any interest you. Unsubscribe | Manage preferences",
    ...notOutreach({ tags: ['newsletter', 'target-area-words'], ambiguous: true }),
  },
  {
    id: 'hard-healthcare-ops-ai',
    sender: 'Victor Hale <victor@bedflow.ai>',
    subject: 'BedFlow - Principal Engineer',
    body: "Hi Edison, BedFlow's AI predicts hospital bed demand and discharge timing so administrators can staff wards efficiently. Principal Engineer role, $280k.",
    ...out('keep_warm', { tags: ['trap-health-admin'], ambiguous: true }),
  },

  // --- Excluded companies: outreach, but ignore --------------------------
  {
    id: 'ex-initech',
    sender: 'Bill Lumbergh <bill@initech.com>',
    subject: 'Staff Engineer at Initech',
    body: "Hi Edison, Initech is hiring a Staff Engineer for our TPS platform. $280k. Yeah, if you could give me a call that'd be great.",
    ...out('ignore', { tags: ['excluded'] }),
  },
  {
    id: 'ex-globex-climate',
    sender: 'Hank Scorpio <hank@globex.com>',
    subject: 'Globex Climate - Head of Engineering',
    body: "Edison, Globex is launching a climate division building grid-scale storage. We'd love you to lead engineering. $350k + equity.",
    ...out('ignore', { tags: ['excluded', 'target-area-words'] }),
  },
  {
    id: 'ex-initech-via-agency',
    sender: 'Paula Reyes <paula@staffingplus.com>',
    subject: 'Principal role - Initech',
    body: 'Hi Edison, I am recruiting for Initech, who is hiring a Principal Engineer to modernize their reporting stack. $300k. Would you be interested?',
    ...out('ignore', { tags: ['excluded', 'via-agency'] }),
  },
]
