from src.storage import VacancyStorage

with VacancyStorage() as storage:
    test_vac = {
        "url": "https://hh.ru/test",
        "name": "Test Engineer",
        "company": "Test Corp",
        "city": "Moscow",
        "salary": "100k",
        "requirements": "Python",
    }
    test_vacancies_list = [
        {
            "name": "Старший сетевой инженер",
            "company": "БЮРО 1440",
            "salary": "250000",
            "requirements": "Опыт от 3 лет на позиции сетевого инженера, NetOps; Продвинутый уровень знаний сетевых технологий, стека TCP/IP, принципов коммутации (VLAN, STP, LACP), динамической маршрутизации (BGP, OSPF, ISIS), работы межсетевого экранирования, работы технологий построения оверлейных сетей и туннелирования; Практические навыки работы с оборудованием крупных вендоров (Juniper, Huawei, Eltex и др); Знание языков программирования Python/Go; Навыки администрирования Linux; Понимание и опыт работы с системами мониторинга инфраструктуры.",
            "url": "https://hh.ru/vacancy/136405560",
        },
        {
            "name": "Ведущий сетевой инженер",
            "company": "Hoff Tech",
            "salary": "null",
            "requirements": "Знания сетей на уровне CCNP/JNCP/HCIP; Опыт работы с маршрутизаторами и коммутаторами Cisco от 3-х лет; Опыт работы с серверными системами Linux; Будет плюсом: опыт разработки (Python, Git), работа с оборудованием Mikrotik/Ubiquiti/UserGate/Континент, умение писать Ansible playbooks, работа с прокси-серверами (Squid, Symantec), системы мониторинга и логирования (ELK, Zabbix, Grafana, Prometheus).",
            "url": "",
        },
    ]
    # test_vacancies_list = [
    #     {
    #         "url": "https://hh.ru/test_dict",
    #         "name": "Test Engineer",
    #         "company": "Test Corp",
    #         "city": "Moscow",
    #         "salary": "100k",
    #         "requirements": "Python",
    #     },
    #     {
    #         "url": "https://hh.ru/test_dict2",
    #         "name": "Test Engineer",
    #         "company": "Test Corp",
    #         "city": "Moscow",
    #         "salary": "100k",
    #         "requirements": "Python",
    #     },
    # ]
    # print(storage.add_vacancy(test_vac))  # True/False
# print(storage.add_vacancies(test_vacancies_list))
# print(storage.get_all())
# print(storage.get_by_url(""))
# print(storage.get_by_date("2026-09-08","2026-09-09"))
# print(storage.count())

print(storage.exists("http//hh.ru/vacancy/136945995"))