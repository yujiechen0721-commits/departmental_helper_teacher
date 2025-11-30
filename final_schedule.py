'''
修改
    1. 加入碩士班課程、課程資料也開放上傳多檔案
    2. 三班排課嘗試
    3. 不同檔案編碼加入
    4. 欄位自動偵測，只需特定欄位
    5. 輔導課標示、單雙週安排
'''

import streamlit as st
import pandas as pd
import numpy as np
import random
import os
from collections import defaultdict
import copy
import zipfile
from io import BytesIO
import tempfile
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 使用非互動式後端
plt.rcParams['font.family'] = ['Microsoft JhengHei', 'sans-serif']  # 支援中文

class CourseScheduler:
    def __init__(self, courses_df, teacher_files):
        self.courses_df = courses_df
        self.teacher_files = teacher_files
        
        # 節次對應時間
        self.period_to_time = {
            1: '08:10-09:00', 2: '09:10-10:00', 3: '10:10-11:00', 4: '11:10-12:00',
            'E': '12:10-13:00', 5: '13:10-14:00', 6: '14:10-15:00', 
            7: '15:10-16:00', 8: '16:10-17:00', 9: '17:10-18:00'
        }
        
        # 星期對應
        self.weekday_map = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4}
        self.weekday_reverse = {0: '一', 1: '二', 2: '三', 3: '四', 4: '五'}
        
        # 讀取教師可用時間
        self.teacher_availability = self.load_teacher_availability()
        
        # 處理課程資料
        self.process_courses()
        
    def load_teacher_availability(self):
        """載入所有教師的可用時間"""
        availability = {}
        
        for teacher_file in self.teacher_files:
            teacher_name = teacher_file.name.replace('.csv', '')
            
            try:
                df = pd.read_csv(teacher_file)
                
                # 建立可用時間表 [星期][節次] = 可用(True/False)
                teacher_slots = {}
                weekdays = ['一', '二', '三', '四', '五']
                
                for day in weekdays:
                    if day in df.columns:
                        teacher_slots[day] = {}
                        for idx, row in df.iterrows():
                            period = row['節次']
                            value = row[day]
                            
                            # 標準化節次
                            if pd.isna(period):
                                continue
                            
                            # 將節次轉換為標準格式
                            if isinstance(period, str):
                                period_key = period.strip()
                            elif isinstance(period, (int, float)):
                                period_key = int(period)
                            else:
                                period_key = period
                            
                            # 0或'0'表示不可排課，空白或其他值表示可排課
                            if pd.isna(value):
                                is_available = True
                            elif isinstance(value, str):
                                is_available = (value.strip() != '0')
                            else:
                                is_available = (value != 0)
                            
                            teacher_slots[day][period_key] = is_available
                
                availability[teacher_name] = teacher_slots
                st.write(f"✓ 載入教師 **{teacher_name}** 的可用時間")
                
                # 顯示不可用時段
                unavailable = []
                for day in weekdays:
                    if day in teacher_slots:
                        for period, available in teacher_slots[day].items():
                            if not available:
                                unavailable.append(f"星期{day}節次{period}")
                if unavailable:
                    st.write(f"  ➤ 不可用時段: {', '.join(unavailable[:10])}{'...' if len(unavailable) > 10 else ''}")
                
            except Exception as e:
                st.warning(f"無法讀取 {teacher_file.name}: {e}")
        
        return availability
    
    def parse_periods(self, periods_str):
        """解析節數字串為列表，處理分號分隔"""
        if pd.isna(periods_str):
            return []
        periods_str = str(periods_str).strip()
        
        # 處理分號分隔
        if ';' in periods_str:
            parts = periods_str.split(';')
        else:
            parts = periods_str.split(',')
        
        result = []
        for p in parts:
            p = p.strip()
            if p.isdigit():
                result.append(int(p))
            elif p == 'E':
                result.append('E')
            elif p:
                result.append(p)
        
        return result
    
    def process_courses(self):
        """處理課程資料，分離已排課和待排課"""
        self.scheduled_courses = []
        self.to_schedule_courses = []
        self.course_groups = defaultdict(list)
        
        for idx, row in self.courses_df.iterrows():
            course_info = {
                'index': idx,
                '系所': row['系所'],
                '班級': str(row['班級']).strip(),
                '科目代碼': row['科目代碼'],
                '科目名稱': row['科目名稱'],
                '組別': str(row['組別']).strip() if pd.notna(row['組別']) else '',
                '修選別': row['修選別'],
                '時數': row['時數'],
                '授課教師': str(row['授課教師']).strip(),
                '星期': str(row['星期']).strip() if pd.notna(row['星期']) else None,
                '節數': row['節數'] if pd.notna(row['節數']) else None,
                '課程安排方式': row['課程安排方式']
            }
            
            # 分離已排課和待排課
            if course_info['星期'] is not None and course_info['星期'] not in ['', 'nan']:
                course_info['節數_列表'] = self.parse_periods(course_info['節數'])
                self.scheduled_courses.append(course_info)
            else:
                self.to_schedule_courses.append(course_info)
                key = (row['科目代碼'], row['課程安排方式'])
                self.course_groups[key].append(course_info)
        
        st.write(f"📊 已排課程: **{len(self.scheduled_courses)}** 門")
        st.write(f"📊 待排課程: **{len(self.to_schedule_courses)}** 門")
    
    def get_available_slots(self, course):
        """獲取課程的可用時段"""
        time_hours = course['時數']
        is_required = course['修選別'] == 1
        group = course['組別']
        
        slots = []
        
        # 第二專長的特殊時段
        if group == '第二專長':
            special_slots = [
                ('一', [1, 2, 3, 4]),
                ('三', [5, 6, 7, 8]),
                ('五', [5, 6, 7, 8]),
            ]
            for day, periods in special_slots:
                if time_hours == 2:
                    slots.append((day, periods[:2]))
                    slots.append((day, periods[2:4]))
                elif time_hours == 3:
                    slots.append((day, periods[:3]))
                elif time_hours == 4:
                    slots.append((day, periods))
            return slots
        
        weekdays = ['一', '二', '三', '四', '五']
        is_remote = (group == '遠距' or '遠距' in str(group))
        
        if time_hours == 2:
            for day in weekdays:
                if is_remote:
                    slots.append((day, [1, 2]))
                slots.append((day, [3, 4]))
                slots.append((day, [5, 6]))
                slots.append((day, [7, 8]))
        
        elif time_hours == 3:
            for day in weekdays:
                slots.append((day, [3, 4, 'E']))
                if not is_required:
                    slots.append((day, ['E', 5, 6]))
                slots.append((day, [7, 8, 9]))
        
        elif time_hours == 4:
            for day in weekdays:
                if is_remote:
                    slots.append((day, [1, 2, 3, 4]))
                slots.append((day, [5, 6, 7, 8]))
        
        return slots
    
    def check_teacher_available(self, teacher, day, periods):
        """檢查教師在指定時段是否可用"""
        if teacher == '無' or teacher == 'nan' or not teacher or pd.isna(teacher):
            return True
            
        if teacher not in self.teacher_availability:
            return True
        
        teacher_slots = self.teacher_availability[teacher]
        if day not in teacher_slots:
            return True
        
        for period in periods:
            if isinstance(period, int):
                check_period = period
            elif period == 'E':
                check_period = 'E'
            else:
                check_period = period
            
            if check_period not in teacher_slots[day]:
                found = False
                for key in teacher_slots[day].keys():
                    if str(key) == str(check_period):
                        if not teacher_slots[day][key]:
                            return False
                        found = True
                        break
                if not found:
                    continue
            else:
                if not teacher_slots[day][check_period]:
                    return False
        
        return True
    
    def check_conflict(self, schedule, course, day, periods):
        """檢查是否有衝突"""
        classes = [c.strip() for c in course['班級'].split(';')]
        teacher = course['授課教師']
        
        for scheduled in schedule:
            scheduled_day = scheduled.get('安排星期')
            scheduled_periods = scheduled.get('安排節數', scheduled.get('節數_列表', []))
            
            if not scheduled_day or not scheduled_periods:
                continue
            
            if scheduled_day != day:
                continue
            
            overlap = set(periods) & set(scheduled_periods)
            if not overlap:
                continue
            
            scheduled_classes = [c.strip() for c in scheduled['班級'].split(';')]
            if set(classes) & set(scheduled_classes):
                return True
            
            if teacher not in ['無', 'nan', ''] and scheduled['授課教師'] not in ['無', 'nan', '']:
                if scheduled['授課教師'] == teacher:
                    return True
        
        return False
    
    def create_individual(self):
        """創建一個染色體（排課方案）"""
        schedule = []
        
        for course in self.scheduled_courses:
            schedule.append({
                **course,
                '安排星期': course['星期'],
                '安排節數': course['節數_列表'],
                '選擇的課程安排方式': course['課程安排方式']
            })
        
        processed_codes = set()
        
        for course in self.to_schedule_courses:
            code = course['科目代碼']
            
            if code in processed_codes:
                continue
            
            method1_courses = [c for c in self.to_schedule_courses 
                              if c['科目代碼'] == code and c['課程安排方式'] == 1]
            method2_courses = [c for c in self.to_schedule_courses 
                              if c['科目代碼'] == code and c['課程安排方式'] == 2]
            
            if not method1_courses and not method2_courses:
                method0_courses = [c for c in self.to_schedule_courses 
                                  if c['科目代碼'] == code]
                for c in method0_courses:
                    slots = self.get_available_slots(c)
                    random.shuffle(slots)
                    
                    assigned = False
                    for day, periods in slots:
                        if self.check_teacher_available(c['授課教師'], day, periods):
                            if not self.check_conflict(schedule, c, day, periods):
                                schedule.append({
                                    **c,
                                    '安排星期': day,
                                    '安排節數': periods,
                                    '選擇的課程安排方式': 0
                                })
                                assigned = True
                                break
                    
                    if not assigned:
                        schedule.append({
                            **c,
                            '安排星期': None,
                            '安排節數': [],
                            '選擇的課程安排方式': 0
                        })
                
                processed_codes.add(code)
                continue
            
            success = True
            temp_schedule = []
            
            if method1_courses:
                for c in method1_courses:
                    slots = self.get_available_slots(c)
                    random.shuffle(slots)
                    
                    assigned = False
                    for day, periods in slots:
                        if self.check_teacher_available(c['授課教師'], day, periods):
                            if not self.check_conflict(schedule + temp_schedule, c, day, periods):
                                temp_schedule.append({
                                    **c,
                                    '安排星期': day,
                                    '安排節數': periods,
                                    '選擇的課程安排方式': 1
                                })
                                assigned = True
                                break
                    
                    if not assigned:
                        success = False
                        break
                
                if success:
                    schedule.extend(temp_schedule)
                    processed_codes.add(code)
                    continue
            
            if method2_courses:
                temp_schedule = []
                success = True
                
                for c in method2_courses:
                    slots = self.get_available_slots(c)
                    random.shuffle(slots)
                    
                    assigned = False
                    for day, periods in slots:
                        if self.check_teacher_available(c['授課教師'], day, periods):
                            if not self.check_conflict(schedule + temp_schedule, c, day, periods):
                                temp_schedule.append({
                                    **c,
                                    '安排星期': day,
                                    '安排節數': periods,
                                    '選擇的課程安排方式': 2
                                })
                                assigned = True
                                break
                    
                    if not assigned:
                        success = False
                        break
                
                if success:
                    schedule.extend(temp_schedule)
            
            processed_codes.add(code)
        
        return schedule
    
    def fitness(self, schedule):
        """計算適應度"""
        score = 0
        penalties = 0
        
        scheduled_count = len([s for s in schedule if s.get('安排星期') is not None])
        score += scheduled_count * 100
        
        for i, course1 in enumerate(schedule):
            if course1.get('安排星期') is None:
                continue
                
            for course2 in schedule[i+1:]:
                if course2.get('安排星期') is None:
                    continue
                
                if course1['安排星期'] == course2['安排星期']:
                    overlap = set(course1.get('安排節數', [])) & set(course2.get('安排節數', []))
                    if overlap:
                        classes1 = set([c.strip() for c in course1['班級'].split(';')])
                        classes2 = set([c.strip() for c in course2['班級'].split(';')])
                        if classes1 & classes2:
                            penalties += 50
                        
                        teacher1 = course1['授課教師']
                        teacher2 = course2['授課教師']
                        if teacher1 not in ['無', 'nan', ''] and teacher2 not in ['無', 'nan', '']:
                            if teacher1 == teacher2:
                                penalties += 50
        
        return score - penalties
    
    def crossover(self, parent1, parent2):
        """交叉"""
        child = [c for c in parent1 if c in self.scheduled_courses]
        
        to_schedule = [c for c in parent1 if c not in self.scheduled_courses]
        for course in to_schedule:
            if random.random() < 0.5:
                child.append(course)
            else:
                matching = [c for c in parent2 
                           if c.get('科目代碼') == course.get('科目代碼') 
                           and c.get('組別') == course.get('組別')]
                if matching:
                    child.append(matching[0])
                else:
                    child.append(course)
        
        return child
    
    def mutate(self, schedule):
        """變異"""
        schedule = copy.deepcopy(schedule)
        
        to_schedule = [i for i, c in enumerate(schedule) 
                      if c not in self.scheduled_courses and c.get('安排星期') is not None]
        
        if not to_schedule:
            return schedule
        
        idx = random.choice(to_schedule)
        course = schedule[idx]
        
        slots = self.get_available_slots(course)
        random.shuffle(slots)
        
        for day, periods in slots:
            if self.check_teacher_available(course['授課教師'], day, periods):
                temp_schedule = [s for i, s in enumerate(schedule) if i != idx]
                if not self.check_conflict(temp_schedule, course, day, periods):
                    schedule[idx]['安排星期'] = day
                    schedule[idx]['安排節數'] = periods
                    break
        
        return schedule
    
    def run_ga(self, population_size=100, generations=200, progress_bar=None):
        """執行遺傳演算法"""
        population = [self.create_individual() for _ in range(population_size)]
        
        best_solution = None
        best_fitness = float('-inf')
        
        for gen in range(generations):
            fitness_scores = [(self.fitness(ind), ind) for ind in population]
            fitness_scores.sort(reverse=True, key=lambda x: x[0])
            
            if fitness_scores[0][0] > best_fitness:
                best_fitness = fitness_scores[0][0]
                best_solution = copy.deepcopy(fitness_scores[0][1])
            
            if progress_bar:
                progress_bar.progress((gen + 1) / generations)
            
            elite_size = population_size // 10
            new_population = [ind for _, ind in fitness_scores[:elite_size]]
            
            while len(new_population) < population_size:
                parent1 = random.choice(fitness_scores[:population_size//2])[1]
                parent2 = random.choice(fitness_scores[:population_size//2])[1]
                
                child = self.crossover(parent1, parent2)
                
                if random.random() < 0.2:
                    child = self.mutate(child)
                
                new_population.append(child)
            
            population = new_population
        
        return best_solution, best_fitness
    
    def generate_results(self, schedule):
        """生成排課結果"""
        results = {}
        
        # 收集所有班級
        all_classes = set()
        for course in schedule:
            classes = [c.strip() for c in course['班級'].split(';')]
            all_classes.update(classes)
        
        # 為每個班級產生課表
        for class_name in sorted(all_classes):
            class_schedule = []
            
            for course in schedule:
                classes = [c.strip() for c in course['班級'].split(';')]
                if class_name in classes:
                    if course.get('安排星期') is not None:
                        periods_str = ';'.join(map(str, course['安排節數']))
                        
                        class_schedule.append({
                            '科目代碼': course['科目代碼'],
                            '科目名稱': course['科目名稱'],
                            '組別': course['組別'],
                            '修選別': '必修' if course['修選別'] == 1 else '選修',
                            '時數': course['時數'],
                            '授課教師': course['授課教師'],
                            '安排星期': course['安排星期'],
                            '安排節數': periods_str,
                            '選擇的課程安排方式': course.get('選擇的課程安排方式', 0)
                        })
            
            if class_schedule:
                df = pd.DataFrame(class_schedule)
                weekday_order = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}
                df['排序_星期'] = df['安排星期'].map(weekday_order)
                
                def parse_first_period(x):
                    first = x.split(';')[0] if ';' in x else x
                    if first == 'E':
                        return 4.5
                    try:
                        return int(first)
                    except:
                        return 0
                
                df['排序_節數'] = df['安排節數'].apply(parse_first_period)
                df = df.sort_values(['排序_星期', '排序_節數'])
                df = df.drop(['排序_星期', '排序_節數'], axis=1)
                
                results[class_name] = df
        
        # 未排課程
        unscheduled = []
        for course in self.to_schedule_courses:
            found = False
            for s in schedule:
                if (s.get('科目代碼') == course['科目代碼'] and 
                    s.get('組別') == course['組別'] and
                    s.get('安排星期') is not None):
                    found = True
                    break
            
            if not found:
                unscheduled.append({
                    '科目代碼': course['科目代碼'],
                    '科目名稱': course['科目名稱'],
                    '班級': course['班級'],
                    '組別': course['組別'],
                    '授課教師': course['授課教師'],
                    '時數': course['時數'],
                    '課程安排方式': course['課程安排方式']
                })
        
        # 衝突檢查
        conflicts = self.check_conflicts(schedule)
        
        return results, unscheduled, conflicts
    
    def check_conflicts(self, schedule):
        """檢查衝突"""
        conflicts = []
        
        for i, course1 in enumerate(schedule):
            if course1.get('安排星期') is None:
                continue
            
            expected_periods = course1['時數']
            actual_periods = len(course1.get('安排節數', []))
            if expected_periods != actual_periods:
                periods_str = ';'.join(map(str, course1.get('安排節數', [])))
                conflicts.append({
                    '衝突類型': '時數不符',
                    '課程1': f"{course1['科目名稱']} ({course1['班級']})",
                    '時間1': f"{course1['安排星期']} 節次:{periods_str}",
                    '課程2': '',
                    '時間2': '',
                    '說明': f"時數為{expected_periods}但排了{actual_periods}節"
                })
            
            for course2 in schedule[i+1:]:
                if course2.get('安排星期') is None:
                    continue
                
                if course1['安排星期'] != course2['安排星期']:
                    continue
                
                overlap = set(course1.get('安排節數', [])) & set(course2.get('安排節數', []))
                if not overlap:
                    continue
                
                periods1_str = ';'.join(map(str, course1.get('安排節數', [])))
                periods2_str = ';'.join(map(str, course2.get('安排節數', [])))
                
                classes1 = set([c.strip() for c in course1['班級'].split(';')])
                classes2 = set([c.strip() for c in course2['班級'].split(';')])
                common_classes = classes1 & classes2
                if common_classes:
                    conflicts.append({
                        '衝突類型': '班級時間衝突',
                        '課程1': f"{course1['科目名稱']} ({course1['班級']})",
                        '時間1': f"{course1['安排星期']} 節次:{periods1_str}",
                        '課程2': f"{course2['科目名稱']} ({course2['班級']})",
                        '時間2': f"{course2['安排星期']} 節次:{periods2_str}",
                        '說明': f"班級 {','.join(common_classes)} 時間重疊"
                    })
                
                teacher1 = course1['授課教師']
                teacher2 = course2['授課教師']
                if teacher1 not in ['無', 'nan', ''] and teacher2 not in ['無', 'nan', '']:
                    if teacher1 == teacher2:
                        conflicts.append({
                            '衝突類型': '教師時間衝突',
                            '課程1': f"{course1['科目名稱']} ({course1['班級']})",
                            '時間1': f"{course1['安排星期']} 節次:{periods1_str}",
                            '課程2': f"{course2['科目名稱']} ({course2['班級']})",
                            '時間2': f"{course2['安排星期']} 節次:{periods2_str}",
                            '說明': f"教師 {teacher1} 時間重疊"
                        })
        
        return conflicts


def create_timetable_image(df, class_name):
    """為單一班級創建課表圖片"""
    # 星期轉換對照表
    day_map = {
        "一": "星期一", "二": "星期二", "三": "星期三",
        "四": "星期四", "五": "星期五", "六": "星期六", "日": "星期日"
    }
    
    # 節次順序與時間對照
    period_order = ["1", "2", "3", "4", "E", "5", "6", "7", "8", "9"]
    period_time = {
        "1": "08:10-09:00", "2": "09:10-10:00", "3": "10:10-11:00",
        "4": "11:10-12:00", "E": "12:10-13:00", "5": "13:10-14:00",
        "6": "14:10-15:00", "7": "15:10-16:00", "8": "16:10-17:00",
        "9": "17:10-18:00"
    }
    
    days = ["星期一", "星期二", "星期三", "星期四", "星期五"]
    
    # 創建副本並轉換星期
    df_copy = df.copy()
    df_copy["安排星期"] = df_copy["安排星期"].map(day_map)
    
    # 初始化課表
    timetable = pd.DataFrame("", index=period_order, columns=days)
    
    # 填入課程資料
    for _, row in df_copy.iterrows():
        day = row["安排星期"]
        if pd.isna(day) or day not in timetable.columns:
            continue
            
        subject = str(row["科目名稱"])
        teacher = row.get("授課教師", "")
        text = f"{subject}\n{teacher}" if pd.notna(teacher) and teacher.strip() and teacher != "無" else subject
        
        # 解析節數
        periods_list = [p.strip() for p in str(row["安排節數"]).split(";") if p.strip()]
        
        for p in periods_list:
            if p in timetable.index:
                if timetable.at[p, day] == "":
                    timetable.at[p, day] = text
                else:
                    timetable.at[p, day] += "\n" + text
    
    # 節次標籤
    row_labels = [f"{p}節\n{period_time[p]}" for p in period_order]
    
    # 繪製課表
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.axis("off")
    
    table = ax.table(
        cellText=timetable.values,
        rowLabels=row_labels,
        colLabels=timetable.columns,
        cellLoc="center",
        loc="center"
    )
    
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.2, 2.5)
    
    # 使用更安全的方式設定表格樣式
    try:
        # 獲取所有單元格
        cells = table.get_celld()
        
        # 設定標題行（第0行）
        for col in range(-1, len(days)):
            if (0, col) in cells:
                cell = cells[(0, col)]
                if col == -1:
                    cell.set_facecolor('#D9E1F2')
                    cell.set_text_props(weight='bold')
                else:
                    cell.set_facecolor('#4472C4')
                    cell.set_text_props(weight='bold', color='white')
                cell.set_edgecolor('#666666')
                cell.set_linewidth(1.5)
        
        # 設定資料行
        for row in range(1, len(period_order) + 1):
            for col in range(-1, len(days)):
                if (row, col) in cells:
                    cell = cells[(row, col)]
                    if col == -1:
                        # 節次標籤列
                        cell.set_facecolor('#D9E1F2')
                        cell.set_text_props(weight='bold', size=7)
                    else:
                        # 內容格
                        cell.set_facecolor('#FFFFFF')
                        cell.set_text_props(size=8)
                    cell.set_edgecolor('#CCCCCC')
                    cell.set_linewidth(1)
    
    except Exception as e:
        st.warning(f"設定表格樣式時發生警告: {e}")
    
    plt.title(f"{class_name} 班級課表", fontsize=18, pad=25, weight='bold')
    
    # 儲存到 BytesIO
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format='png', dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    img_buffer.seek(0)
    
    return img_buffer


def create_zip_file(results, unscheduled, conflicts):
    """創建包含所有結果的ZIP檔案（包含CSV和PNG）"""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # 寫入各班級課表（CSV）
        for class_name, df in results.items():
            csv_buffer = BytesIO()
            df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            zip_file.writestr(f'{class_name}課程排課結果.csv', csv_buffer.getvalue())
            
            # 寫入課表圖片（PNG）
            try:
                img_buffer = create_timetable_image(df, class_name)
                zip_file.writestr(f'{class_name}_課表.png', img_buffer.getvalue())
            except Exception as e:
                st.warning(f"生成 {class_name} 課表圖片時發生錯誤: {e}")
        
        # 寫入未排課程
        if unscheduled:
            df_unscheduled = pd.DataFrame(unscheduled)
            csv_buffer = BytesIO()
            df_unscheduled.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            zip_file.writestr('未排課程.csv', csv_buffer.getvalue())
        
        # 寫入衝突報告
        if conflicts:
            df_conflicts = pd.DataFrame(conflicts)
            csv_buffer = BytesIO()
            df_conflicts.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            zip_file.writestr('衝突報告.csv', csv_buffer.getvalue())
    
    zip_buffer.seek(0)
    return zip_buffer


# Streamlit 介面
def main():
    st.set_page_config(page_title="GA 排課系統", page_icon="📚", layout="wide")
    
    st.title("🎓 GA 排課系統")
    st.markdown("---")
    
    # 側邊欄
    with st.sidebar:
        st.header("⚙️ 參數設定")
        population_size = st.slider("種群大小", 50, 200, 100, 10)
        generations = st.slider("世代數", 50, 500, 200, 50)
        
        st.markdown("---")
        st.header("📖 排課規則")
        st.markdown("""
        1. 同班級課程時間不重疊
        2. 同教師課程時間不重疊
        3. 多班級課程不衝堂
        4. 尊重已排定課程
        5. 2小時課程不排12:00-13:00
        6. 必修3小時課程不跨午休
        7. 第二專長有特殊時段
        8. 尊重教師可用時間
        9. **除遠距課程外，不排1、2節**
        """)
    
    # 主要內容
    st.header("📁 步驟 1: 上傳檔案")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("上傳課程資料")
        courses_file = st.file_uploader(
            "上傳 courses.csv",
            type=['csv'],
            help="包含系所、班級、科目代碼等欄位的課程資料"
        )
        
        if courses_file:
            st.success("✓ 課程檔案已上傳")
            try:
                df_preview = pd.read_csv(courses_file)
                st.write(f"共 {len(df_preview)} 筆課程資料")
                with st.expander("預覽課程資料"):
                    st.dataframe(df_preview.head(10))
                courses_file.seek(0)  # 重置檔案指標
            except Exception as e:
                st.error(f"讀取課程檔案失敗: {e}")
    
    with col2:
        st.subheader("上傳教師可用時間")
        teacher_files = st.file_uploader(
            "上傳教師 CSV 檔案（可多選）",
            type=['csv'],
            accept_multiple_files=True,
            help="每位教師一個CSV檔案，檔名為教師姓名"
        )
        
        if teacher_files:
            st.success(f"✓ 已上傳 {len(teacher_files)} 位教師的資料")
            with st.expander("已上傳的教師"):
                for tf in teacher_files:
                    st.write(f"• {tf.name.replace('.csv', '')}")
    
    st.markdown("---")
    
    # 開始排課
    if courses_file and teacher_files:
        st.header("🚀 步驟 2: 開始排課")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            start_button = st.button("🎯 開始排課", type="primary", use_container_width=True)
        with col2:
            st.write("")  # 空白佔位
        
        if start_button:
            try:
                # 讀取課程資料
                courses_df = pd.read_csv(courses_file)
                
                # 重置教師檔案指標
                for tf in teacher_files:
                    tf.seek(0)
                
                # 建立排課器
                st.write("### 📋 初始化排課系統")
                with st.spinner("讀取資料中..."):
                    scheduler = CourseScheduler(courses_df, teacher_files)
                
                # 執行GA
                st.write("### 🧬 執行遺傳演算法")
                st.write(f"種群大小: {population_size} | 世代數: {generations}")
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                with st.spinner("排課中，請稍候..."):
                    best_schedule, best_fitness = scheduler.run_ga(
                        population_size=population_size,
                        generations=generations,
                        progress_bar=progress_bar
                    )
                
                status_text.success(f"✓ 排課完成！最終適應度: {best_fitness}")
                
                # 生成結果
                st.write("### 📊 生成排課結果")
                with st.spinner("生成結果檔案..."):
                    results, unscheduled, conflicts = scheduler.generate_results(best_schedule)
                
                st.markdown("---")
                st.header("📈 排課結果統計")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("已排課程總數", len([s for s in best_schedule if s.get('安排星期')]))
                
                with col2:
                    st.metric("未排課程數", len(unscheduled))
                
                with col3:
                    st.metric("衝突數量", len(conflicts))
                
                # 顯示結果
                st.markdown("---")
                st.header("📋 各班級課表")
                
                # 使用分頁顯示各班級課表
                if results:
                    class_tabs = st.tabs(list(results.keys()))
                    
                    for tab, (class_name, df) in zip(class_tabs, results.items()):
                        with tab:
                            # 顯示課表圖片
                            st.subheader("📅 視覺化課表")
                            try:
                                img_buffer = create_timetable_image(df, class_name)
                                st.image(img_buffer, width='stretch')
                                
                                # 提供圖片下載
                                img_buffer.seek(0)
                                st.download_button(
                                    label="💾 下載課表圖片",
                                    data=img_buffer,
                                    file_name=f"{class_name}_課表.png",
                                    mime="image/png"
                                )
                            except Exception as e:
                                st.error(f"生成課表圖片時發生錯誤: {e}")
                            
                            st.markdown("---")
                            
                            # 顯示課表資料
                            st.subheader("📊 課表資料")
                            st.dataframe(df, width='stretch')
                            
                            # 提供CSV下載
                            csv = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                            st.download_button(
                                label=f"💾 下載 {class_name} 課表 CSV",
                                data=csv,
                                file_name=f"{class_name}課程排課結果.csv",
                                mime="text/csv"
                            )
                
                # 未排課程
                if unscheduled:
                    st.markdown("---")
                    st.header("⚠️ 未排課程")
                    df_unscheduled = pd.DataFrame(unscheduled)
                    st.dataframe(df_unscheduled, width='stretch')
                else:
                    st.success("✅ 所有課程均已成功排課！")
                
                # 衝突報告
                if conflicts:
                    st.markdown("---")
                    st.header("🚨 衝突報告")
                    df_conflicts = pd.DataFrame(conflicts)
                    st.dataframe(df_conflicts, width='stretch')
                else:
                    st.success("✅ 未發現任何衝突！")
                
                # 下載所有結果
                st.markdown("---")
                st.header("💾 下載完整結果")
                
                with st.spinner("正在打包所有結果檔案..."):
                    zip_buffer = create_zip_file(results, unscheduled, conflicts)
                
                st.success("✅ 結果檔案已準備完成！")
                st.info("📦 ZIP檔案包含：各班級CSV課表、各班級PNG課表圖片、未排課程、衝突報告")
                
                st.download_button(
                    label="📦 下載所有結果（ZIP）",
                    data=zip_buffer,
                    file_name="排課結果.zip",
                    mime="application/zip",
                    use_container_width=True,
                    type="primary"
                )
                
            except Exception as e:
                st.error(f"排課過程發生錯誤: {e}")
                st.exception(e)
    
    else:
        st.info("👆 請先上傳課程資料和教師可用時間檔案")
        
        # 顯示範例檔案格式
        with st.expander("📄 查看檔案格式說明"):
            st.subheader("courses.csv 格式")
            st.markdown("""
            必要欄位：
            - 系所
            - 班級（多個班級用 `;` 分隔，如 `1A;1B`）
            - 科目代碼
            - 科目名稱
            - 組別（第二專長、遠距等）
            - 修選別（1=必修, 0=選修）
            - 時數
            - 授課教師
            - 星期（已排課程填寫，如 `一`）
            - 節數（已排課程填寫，用 `;` 分隔，如 `1;2`）
            - 課程安排方式（0, 1, 2）
            """)
            
            st.subheader("教師CSV格式")
            st.markdown("""
            範例：`金凱儀.csv`
            
            | 節次 | 時間 | 一 | 二 | 三 | 四 | 五 |
            |------|------|----|----|----|----|-----|
            | 1 | 08:10-09:00 | 0 | | | | |
            | 2 | 09:10-10:00 | 0 | | | | |
            | ... | ... | ... | ... | ... | ... | ... |
            
            - `0` 表示該時段不可排課
            - 空白表示可排課
            """)


if __name__ == "__main__":
    main()
