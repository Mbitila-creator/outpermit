from forms_builder.models import FormSection

from .models import ConferenceGuidingQuestion, ConferenceGuidingTopic, ConferenceSession


GUIDING_SECTIONS = (
    {
        "condition_value": "BASIC_EDUCATION_17_AUG",
        "session": "Basic Education Session",
        "title": "Subtopic 1: Shifting to Competency: Strengthening Foundational Learning and 21st-Century Skills",
        "questions": (
            "How can Tanzania effectively implement its revised competency-based curriculum to ensure that competency-based learning is realized in classroom practice while strengthening foundational literacy and numeracy?",
            "Which specific cognitive, social-emotional, and technical skills must be prioritized at the primary and lower-secondary levels to prepare learners for a rapidly changing, innovation-driven economy?",
            "In what ways does early exposure to skill-based, hands-on learning directly catalyze a culture of creativity and entrepreneurship among young learners?",
        ),
    },
    {
        "condition_value": "BASIC_EDUCATION_17_AUG",
        "session": "Basic Education Session",
        "title": "Subtopic 2: Building a Sustainable Ecosystem: Strategic Partnerships and Systemic Reforms",
        "questions": (
            "How can strategic collaborations among the government, schools, local communities, and the private sector be leveraged to co-design and deliver relevant, sustainable skill-development programs?",
            "What specific policy, financing, and institutional reforms are urgently required to sustain a competency-based education model over the long term?",
            "How should learning outcomes and system progress be measured to ensure these skill-based reforms are effective, equitable, and scalable across all regions of Tanzania?",
        ),
    },
    {
        "condition_value": "HIGHER_EDUCATION_TVET_19_AUG",
        "session": "Higher Education and TVET Session - Higher Education",
        "title": "Subtopic 1: Preparing Higher Education Institutions for the Future: Innovation, Agility and Institutional Transformation",
        "questions": (
            "How can the university community change from being critics of transformation to drivers of innovations especially when adopting new digital and pedagogical models? OR What specific incentives or structural change can universities use to encourage students and staff to accept and champion new ideas?",
            "What is the biggest operational barrier to agility in the Tanzanian higher education system and how the challenge can be addressed to enhance the contribution of higher education institutions in the realization of the DIRA 2050?",
            "What new financial models’ higher education must adopt to sustain long-term institutional transformation?",
            "What strategies Tanzanian universities adopt to enhance transformation and shift from teaching fixed, traditional curricula to cultivating flexible, lifelong skills that match the future of work?",
        ),
    },
    {
        "condition_value": "HIGHER_EDUCATION_TVET_19_AUG",
        "session": "Higher Education and TVET Session - Higher Education",
        "title": "Subtopic 2: Building Stronger Higher Education-Industry Partnerships for Workforce Readiness and Economic Growth",
        "questions": (
            "Apart from frameworks what operational changes are needed to strengthen collaboration between Tanzanian higher learning institutions and industries to ensure graduates are job-ready?",
            "Instead of full-duration degrees, how can universities partner with industry to launch short, stackable programmes that add value to traditional degrees and provide the skills employers need?",
            "What strategies higher education-industry partnership can adopt to build sustainable partnership and ensure return to the industry?",
            "How can higher education-industry partnership accelerate the transition toward a knowledge-based economy, in alignment with aspirations of Tanzania Development Vision 2050 (DIRA 2050)?",
        ),
    },
    {
        "condition_value": "HIGHER_EDUCATION_TVET_19_AUG",
        "session": "Higher Education and TVET Session - TVET",
        "title": "Subtopic 3: Transforming Apprenticeship Systems for Future Skills and Decent Employment in Tanzania",
        "questions": (
            "How can apprenticeship systems be strengthened to meet future labour market demands?",
            "What incentives should be provided to industries to increase apprenticeship placements?",
            "How can informal apprenticeships be recognized and integrated into the national qualifications’ framework?",
            "What roles should government, employers and TVET institutions play in expanding apprenticeships?",
            "How can apprenticeship programmes improve graduate employability and productivity?",
        ),
    },
    {
        "condition_value": "HIGHER_EDUCATION_TVET_19_AUG",
        "session": "Higher Education and TVET Session - TVET",
        "title": "Subtopic 4: Building a Future-Ready TVET Ecosystem for Industrialization, Innovation and Inclusive Economic Growth towards Tanzania Vision 2050",
        "questions": (
            "What reforms are needed to make TVET responsive to Vision 2050?",
            "Which future skills will be most critical for Tanzania's economic transformation?",
            "How can Centres of Excellence support industrialization and innovation?",
            "How can public-private partnerships strengthen TVET quality and relevance?",
            "What financing mechanisms will ensure sustainable investment in skills development?",
        ),
    },
    {
        "condition_value": "STI_21_AUG",
        "session": "Science, Technology and Innovation Session",
        "title": "Subtopic 1: Architecting a Resilient STI Ecosystem for Tanzania’s High-Income Transition",
        "questions": (
            "How must Tanzania’s STI ecosystem structurally evolve to shift the national economy from resource dependency to a knowledge- and innovation-driven model by 2050?",
            "What institutional reforms and human capital strategies are required to cultivate a critical mass of researchers, deep-tech entrepreneurs, and innovation managers, while actively mitigating brain drain?",
            "How can Tanzania strategically integrate emerging technologies (e.g., AI, green energy, and biotechnology) into priority sectors like agriculture and mining to ensure global competitiveness and inclusive wealth creation?",
        ),
    },
    {
        "condition_value": "STI_21_AUG",
        "session": "Science, Technology and Innovation Session",
        "title": "Subtopic 2: Catalysing Strategic STI Investments for Value Addition, Youth Employment, and Global Competitiveness",
        "questions": (
            "How should Tanzania prioritize and sequence strategic STI investments (e.g., agro-processing, mineral beneficiation, and digital infrastructure) to accelerate the transition to a value-added economy?",
            "What public-private partnership models are most effective in aligning higher education and TVET curricula with industry needs to guarantee high-quality, future-proof job creation for Tanzania’s youth?",
            "Which long-term financing mechanisms, intellectual property frameworks, and regulatory sandboxes must be implemented now to attract sustained domestic and foreign direct investment in foundational research and deep-tech?",
        ),
    },
    {
        "condition_value": "STI_21_AUG",
        "session": "Science, Technology and Innovation Session",
        "title": "Subtopic 3: Advancing Technological Sovereignty: Synergizing Indigenous Innovation with Strategic Global Partnerships",
        "questions": (
            "How can Tanzania’s national innovation ecosystem be optimized to accelerate the commercialization of indigenous R&D, thereby reducing reliance on imported technologies?",
            "What regulatory frameworks are most effective for Tanzania to safely absorb, adapt, and co-develop emerging global technologies while safeguarding national intellectual property and data sovereignty?",
            "In what ways can science diplomacy and strategic partnerships be leveraged to secure sustainable investment and market access for home-grown technological solutions without compromising Tanzania's long-term technological autonomy?",
        ),
    },
)


def configure_guiding_questions(event_form):
    created_topics = []
    topic_order_by_session = {}
    for specification in GUIDING_SECTIONS:
        session = ConferenceSession.objects.get(event=event_form.event, registration_option_value=specification["condition_value"])
        topic_order = topic_order_by_session.get(session.pk, 0) + 1
        topic_order_by_session[session.pk] = topic_order
        description = (
            f"{specification['session']}. Respond to any or all of the guiding "
            "questions below before or during the session."
        )
        topic, _ = ConferenceGuidingTopic.objects.update_or_create(
            session=session,
            title=specification["title"],
            defaults={
                "description": description,
                "display_order": topic_order,
                "is_active": True,
            },
        )

        active_labels = []
        for question_order, label in enumerate(specification["questions"], start=1):
            active_labels.append(label)
            ConferenceGuidingQuestion.objects.update_or_create(
                topic=topic,
                text=label,
                defaults={
                    "display_order": question_order,
                    "is_active": True,
                },
            )
        topic.questions.exclude(text__in=active_labels).update(is_active=False)
        created_topics.append(topic)

    FormSection.objects.filter(event_form=event_form, title_en__in=[item["title"] for item in GUIDING_SECTIONS]).update(is_active=False)

    return created_topics

