"""
РГР: Расчет экономической эффективности внедрения ИС
"AI-агент рациона питания"
"""

import json
import math

# Загрузка конфигурации
with open('ai_nutrition_config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Извлечение данных из config
cal = config['calendar_2023']
prog = config['programmer']
category = config['complexity_category']
time_costs = config['time_costs']
pc = config['pc']
pc_maint = config['pc_maintenance']
machine_time = config['machine_time']
materials = config['materials']
profit_norm = config['profit_norm']
efficiency = config['efficiency']

# Коэффициенты по категориям
coefficients = {
    1: {"c": 1.25, "p": 0.05},
    2: {"c": 1.5, "p": 0.1},
    3: {"c": 1.6, "p": 0.5},
    4: {"c": 2.0, "p": 1.0}
}

c = coefficients[category]["c"]
p = coefficients[category]["p"]

print("=" * 60)
print("РАСЧЕТ ЭКОНОМИЧЕСКОЙ ЭФФЕКТИВНОСТИ")
print("AI-АГЕНТ РАЦИОНА ПИТАНИЯ")
print("=" * 60)

# ==================== РАСЧЕТЫ ====================

# 1. Коэффициент сложности внедрения
K = c * (1 + p)
print(f"\n1. Коэффициент сложности внедрения:")
print(f"   K = c × (1 + p) = {c} × (1 + {p}) = {K:.2f}")

# 2. Трудоемкость с учетом сложности
total_fact_time = sum(time_costs.values())
t_razr_sl = total_fact_time * K
print(f"\n2. Трудоемкость разработки с учетом сложности:")
print(f"   Фактические затраты времени: {total_fact_time} часов")
print(f"   t_разр.сл = {total_fact_time} × {K:.2f} = {t_razr_sl:.1f} часов")

# 3. Месячный оклад программиста
K_DOP = 1 + (prog['premium_percent'] + prog['regional_coefficient_percent']) / 100
K_SN = 1 + (prog['insurance_contributions_percent'] / 100)
ZP_MES = prog['monthly_salary'] * K_DOP * K_SN
print(f"\n3. Месячный оклад программиста с учетом надбавок:")
print(f"   Базовый оклад: {prog['monthly_salary']} руб")
print(f"   K_доп = 1 + ({prog['premium_percent']} + {prog['regional_coefficient_percent']})/100 = {K_DOP:.3f}")
print(f"   K_сн = 1 + {prog['insurance_contributions_percent']}/100 = {K_SN:.3f}")
print(f"   ЗП_мес = {prog['monthly_salary']} × {K_DOP:.3f} × {K_SN:.3f} = {ZP_MES:.2f} руб")

# 4. Годовой фонд заработной платы
FZ_RG = ZP_MES * 12
print(f"\n4. Годовой фонд заработной платы:")
print(f"   ФЗР_г = {ZP_MES:.2f} × 12 = {FZ_RG:.2f} руб")

# 5. Число рабочих часов в году
N = cal['total_days']
N_PV = cal['holidays_weekends']
N_PP = cal['pre_holiday_days']
N_SM = cal['work_shift_hours']
n_R = (N - N_PV - N_PP) * N_SM - N_PP * 1
print(f"\n5. Число рабочих часов в году:")
print(f"   n_р = ({N} - {N_PV} - {N_PP}) × {N_SM} - {N_PP} × 1 = {n_R} часов")

# 6. Средняя часовая оплата программиста
C_RAZR = FZ_RG / n_R
print(f"\n6. Средняя часовая оплата программиста:")
print(f"   С_разр = {FZ_RG:.2f} / {n_R} = {C_RAZR:.2f} руб/час")

# 7. Расходы по оплате труда разработчика
Z_RAZR = t_razr_sl * C_RAZR
print(f"\n7. Расходы по оплате труда разработчика:")
print(f"   З_разр = {t_razr_sl:.1f} × {C_RAZR:.2f} = {Z_RAZR:.2f} руб")

# 8. Время профилактики ПК
N_REM = pc_maint['daily_hours'] * 365 + pc_maint['monthly_hours'] * 12 + pc_maint['yearly_hours']
print(f"\n8. Время профилактики ПК в году:")
print(f"   N_рем = {pc_maint['daily_hours']} × 365 + {pc_maint['monthly_hours']} × 12 + {pc_maint['yearly_hours']} = {N_REM} часов")

# 9. Годовой фонд времени работы ПК
n_RPK = (N - N_PV - N_PP) * N_SM - N_PP * 1 - N_REM
print(f"\n9. Годовой фонд времени работы ПК:")
print(f"   n_рпк = {n_R} - {N_REM} = {n_RPK} часов")

# 10. Балансовая стоимость ПК
C_PK = pc['price'] * pc['installation_coefficient']
print(f"\n10. Балансовая стоимость ПК:")
print(f"    Ц_пк = {pc['price']} × {pc['installation_coefficient']} = {C_PK:.2f} руб")

# 11. Годовые отчисления на амортизацию
Z_GAM = C_PK * pc['amortization_rate']
print(f"\n11. Годовые отчисления на амортизацию:")
print(f"    З_гам = {C_PK:.2f} × {pc['amortization_rate']} = {Z_GAM:.2f} руб")

# 12. Затраты на электроэнергию
Z_GEL = pc['power_kw'] * n_RPK * pc['electricity_price_per_kwh'] * pc['intensive_use_coefficient']
print(f"\n12. Затраты на электроэнергию:")
print(f"    З_гэл = {pc['power_kw']} × {n_RPK} × {pc['electricity_price_per_kwh']} × {pc['intensive_use_coefficient']} = {Z_GEL:.2f} руб")

# 13. Текущие затраты на эксплуатацию ПК
Z_GPK = Z_GAM + Z_GEL
print(f"\n13. Текущие затраты на эксплуатацию ПК:")
print(f"    З_гпк = {Z_GAM:.2f} + {Z_GEL:.2f} = {Z_GPK:.2f} руб")

# 14. Себестоимость часа работы на компьютере
S_PK = Z_GPK / n_RPK
print(f"\n14. Себестоимость часа работы на компьютере:")
print(f"    С_пк = {Z_GPK:.2f} / {n_RPK} = {S_PK:.4f} руб/час")

# 15. Трудоемкость использования компьютера
total_machine_time = sum(machine_time.values())
print(f"\n15. Трудоемкость использования компьютера:")
print(f"    Программирование: {machine_time['programming']} часов")
print(f"    Отладка: {machine_time['debugging']} часов")
print(f"    Документация: {machine_time['documentation']} часов")
print(f"    Итого: {total_machine_time} часов")

# 16. Затраты на оплату машинного времени
Z_MV = total_machine_time * S_PK
print(f"\n16. Затраты на оплату машинного времени:")
print(f"    З_мв = {total_machine_time} × {S_PK:.4f} = {Z_MV:.2f} руб")

# 17. Расходные материалы
Z_RM = materials['internet']['cost_per_hour'] * materials['internet']['hours'] + \
       materials['paper']['cost_per_sheet'] * materials['paper']['sheets']
print(f"\n17. Расходные материалы:")
print(f"    Интернет: {materials['internet']['cost_per_hour']} × {materials['internet']['hours']} = {materials['internet']['cost_per_hour'] * materials['internet']['hours']} руб")
print(f"    Бумага: {materials['paper']['cost_per_sheet']} × {materials['paper']['sheets']} = {materials['paper']['cost_per_sheet'] * materials['paper']['sheets']} руб")
print(f"    З_рм = {Z_RM:.2f} руб")

# 18. Общие затраты на создание программы
S_OBSH = Z_RAZR + Z_MV + Z_RM
print(f"\n18. Общие затраты на создание программы:")
print(f"    С_общ = {Z_RAZR:.2f} + {Z_MV:.2f} + {Z_RM:.2f} = {S_OBSH:.2f} руб")

# 19. Предполагаемая цена программного продукта
C_PRICE = S_OBSH * (1 + profit_norm)
print(f"\n19. Предполагаемая цена программного продукта:")
print(f"    Ц = {S_OBSH:.2f} × (1 + {profit_norm}) = {C_PRICE:.2f} руб")

# 20. Расчет экономической эффективности
print(f"\n20. Расчет экономической эффективности:")

# Экономия времени на планировании питания
time_planning_before = efficiency['meal_planning_time_before_minutes'] * efficiency['meal_planning_operations_per_month']
time_planning_after = time_planning_before / efficiency['time_saving_multiplier']
saved_time_planning_hours = (time_planning_before - time_planning_after) / 60
saved_cost_planning = saved_time_planning_hours * efficiency['nutritionist_salary_per_hour']

print(f"    Планирование питания:")
print(f"    - До внедрения: {efficiency['meal_planning_time_before_minutes']} мин × {efficiency['meal_planning_operations_per_month']} раз = {time_planning_before} мин/месяц")
print(f"    - После внедрения: {time_planning_after:.1f} мин/месяц")
print(f"    - Экономия: {saved_time_planning_hours:.2f} часов/месяц")
print(f"    - Стоимость экономии: {saved_cost_planning:.2f} руб/месяц")

# Экономия времени на покупки
time_shopping_after = efficiency['shopping_time_before_hours'] / efficiency['time_saving_multiplier']
saved_time_shopping = efficiency['shopping_time_before_hours'] - time_shopping_after
saved_cost_shopping = saved_time_shopping * efficiency['user_time_value_per_hour']

print(f"    Покупки продуктов:")
print(f"    - До внедрения: {efficiency['shopping_time_before_hours']} часов/месяц")
print(f"    - После внедрения: {time_shopping_after:.2f} часов/месяц")
print(f"    - Экономия: {saved_time_shopping:.2f} часов/месяц")
print(f"    - Стоимость экономии: {saved_cost_shopping:.2f} руб/месяц")

total_saved_cost = saved_cost_planning + saved_cost_shopping
print(f"    Общая экономия в месяц: {total_saved_cost:.2f} руб")

# 21. Срок окупаемости
T_OK = C_PRICE / total_saved_cost
print(f"\n21. Срок окупаемости:")
print(f"    Т_ок = {C_PRICE:.2f} / {total_saved_cost:.2f} = {T_OK:.2f} месяцев ({T_OK/12:.2f} лет)")

print("\n" + "=" * 60)
print("ИТОГОВЫЕ РЕЗУЛЬТАТЫ:")
print("=" * 60)
print(f"Общие затраты на разработку: {S_OBSH:.2f} руб")
print(f"Предполагаемая цена продукта: {C_PRICE:.2f} руб")
print(f"Экономия в месяц: {total_saved_cost:.2f} руб")
print(f"Срок окупаемости: {T_OK:.2f} месяцев ({T_OK/12:.2f} лет)")
print("=" * 60)

# ==================== ФОРМИРОВАНИЕ JSON РЕЗУЛЬТАТОВ ====================

results = {
    "project_name": config['project_name'],
    "formulas": {
        "K": round(K, 2),
        "t_РАЗР_СЛ": round(t_razr_sl, 2),
        "ЗПМЕС": round(ZP_MES, 2),
        "ФЗРГ": round(FZ_RG, 2),
        "nР": round(n_R, 0),
        "СРАЗР": round(C_RAZR, 2),
        "ЗРАЗР": round(Z_RAZR, 2),
        "NРЕМ": round(N_REM, 0),
        "nРПК": round(n_RPK, 0),
        "ЦПК": round(C_PK, 2),
        "ЗГАМ": round(Z_GAM, 2),
        "ЗГЭЛ": round(Z_GEL, 2),
        "ЗГПК": round(Z_GPK, 2),
        "СПК": round(S_PK, 4),
        "tМВ": round(total_machine_time, 0),
        "ЗМВ": round(Z_MV, 2),
        "ЗРМ": round(Z_RM, 2),
        "СОБЩ": round(S_OBSH, 2),
        "Ц": round(C_PRICE, 2),
        "Ток_месяцев": round(T_OK, 2),
        "Ток_лет": round(T_OK / 12, 2)
    },
    "table1_time_costs": {
        "предпроектное_исследование_часы": time_costs['pre_project_research'],
        "предпроектное_исследование_дни": round(time_costs['pre_project_research'] / 8, 1),
        "разработка_ТЗ_часы": time_costs['technical_specification'],
        "разработка_ТЗ_дни": round(time_costs['technical_specification'] / 8, 1),
        "реализация_часы": time_costs['implementation'],
        "реализация_дни": round(time_costs['implementation'] / 8, 1),
        "создание_продукта_часы": time_costs['product_creation'],
        "создание_продукта_дни": round(time_costs['product_creation'] / 8, 1),
        "внедрение_часы": time_costs['deployment'],
        "внедрение_дни": round(time_costs['deployment'] / 8, 1),
        "итого_часы": total_fact_time,
        "итого_дни": round(total_fact_time / 8, 1)
    },
    "table2_complexity": {
        "категория": category,
        "коэффициент_сложности_c": c,
        "коэффициент_коррекции_p": p,
        "коэффициент_сложности_внедрения_K": round(K, 2)
    },
    "table3_materials": {
        "интернет_стоимость_за_единицу": materials['internet']['cost_per_hour'],
        "интернет_количество": materials['internet']['hours'],
        "интернет_общая_стоимость": materials['internet']['cost_per_hour'] * materials['internet']['hours'],
        "бумага_стоимость_за_единицу": materials['paper']['cost_per_sheet'],
        "бумага_количество": materials['paper']['sheets'],
        "бумага_общая_стоимость": materials['paper']['cost_per_sheet'] * materials['paper']['sheets'],
        "итого_ЗРМ": round(Z_RM, 2)
    },
    "table4_total_costs": {
        "общие_затраты_на_зарплату_ЗОБЩ": round(Z_RAZR, 2),
        "расходные_материалы_ЗРМ": round(Z_RM, 2),
        "машинное_время_ЗМВ": round(Z_MV, 2),
        "итого_СОБЩ": round(S_OBSH, 2)
    },
    "table5_efficiency": {
        "планирование_время_до_минуты": efficiency['meal_planning_time_before_minutes'],
        "планирование_время_после_минуты": round(efficiency['meal_planning_time_before_minutes'] / efficiency['time_saving_multiplier'], 1),
        "количество_операций_месяц": efficiency['meal_planning_operations_per_month'],
        "временные_затраты_месяц_минуты": time_planning_before,
        "временные_затраты_месяц_часы": round(time_planning_before / 60, 2),
        "сэкономленное_время_часы": round(saved_time_planning_hours, 2),
        "зарплата_нутрициолога_час": efficiency['nutritionist_salary_per_hour'],
        "стоимость_сэкономленных_временных_затрат_планирование": round(saved_cost_planning, 2),
        "покупки_время_до_часы": efficiency['shopping_time_before_hours'],
        "покупки_время_после_часы": round(time_shopping_after, 2),
        "сэкономленное_время_покупки_часы": round(saved_time_shopping, 2),
        "стоимость_времени_пользователя_час": efficiency['user_time_value_per_hour'],
        "стоимость_сэкономленных_временных_затрат_покупки": round(saved_cost_shopping, 2),
        "общая_стоимость_сэкономленных_временных_затрат_месяц": round(total_saved_cost, 2)
    },
    "summary": {
        "общие_затраты_на_разработку": round(S_OBSH, 2),
        "предполагаемая_цена_продукта": round(C_PRICE, 2),
        "срок_окупаемости_месяцев": round(T_OK, 2),
        "срок_окупаемости_лет": round(T_OK / 12, 2),
        "экономия_в_месяц": round(total_saved_cost, 2)
    },
    "intermediate_calculations": {
        "K_DOP": round(K_DOP, 4),
        "K_SN": round(K_SN, 4),
        "total_fact_time": total_fact_time,
        "N": N,
        "N_PV": N_PV,
        "N_PP": N_PP,
        "N_SM": N_SM
    }
}

# Сохранение результатов в JSON
with open('ai_nutrition_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nРезультаты сохранены в ai_nutrition_results.json")