"""Creates markdown files for static site generation."""

import sqlite3
import os
import json
import yaml
import csv
from typing import List, Dict, Any

# Constants
CURRENT_DIR = os.getcwd()
DB_FILE_PATH = os.path.join("transformed", "transformed_data.db")
MARKDOWN_DIR = os.path.join(CURRENT_DIR, "..", "website", "_program")
full_path = os.path.join(CURRENT_DIR, DB_FILE_PATH)
FISCAL_YEARS = ['2022', '2023', '2024']

def ensure_directory_exists(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)

def get_obligations_data(cursor, program_id, fiscal_years):
    """Get obligations data for specified fiscal years."""
    obligations = []
    for year in fiscal_years:
        year_data = {
            'x': year,
            'sam_estimate': 0.0,
            'sam_actual': 0.0,
            'usa_spending_actual': 0.0
        }

        # Get USA spending obligations - now with aggregation, excluding negative numbers
        cursor.execute("""
            SELECT ROUND(SUM(obligations), 2) as total_obligations 
            FROM usaspending_assistance_obligation_aggregation
            WHERE cfda_number = ? AND action_date_fiscal_year = ?
            GROUP BY cfda_number, action_date_fiscal_year
        """, (program_id, year))
        
        usa_row = cursor.fetchone()
        if usa_row and usa_row['total_obligations'] is not None:
            year_data['usa_spending_actual'] = float(usa_row['total_obligations'])

        # Get SAM spending data and order by is_actual
        cursor.execute("""
            SELECT fiscal_year, assistance_type, amount, is_actual
            FROM program_sam_spending
            WHERE program_id = ? AND fiscal_year = ?
            ORDER BY is_actual DESC
        """, (program_id, year))

        sam_rows = cursor.fetchall()
        
        # Only set sam_estimate if we don't have actual
        if sam_rows:
            if sam_rows[0]['is_actual'] == 1:
                year_data['sam_actual'] = float(sam_rows[0]['amount'])
            else:
                year_data['sam_estimate'] = float(sam_rows[0]['amount'])

        obligations.append(year_data)
    return obligations

def generate_agency_list(cursor: sqlite3.Cursor, program_ids: List[str], fiscal_year: str) -> List[Dict[str, Any]]:
    """Generate list of agencies with program counts and obligations for a set of programs."""
    cursor.execute("""
        WITH program_totals AS (
            SELECT 
                a1.agency_name as agency_title,
                COUNT(DISTINCT p.id) as program_count,
                COALESCE(SUM(CASE 
                    WHEN ps.fiscal_year = ? AND ps.is_actual = 1 
                    THEN ps.amount 
                    ELSE 0 
                END), 0) as total_obs
            FROM program p
            LEFT JOIN agency a ON p.agency_id = a.id
            LEFT JOIN agency a1 ON a.tier_1_agency_id = a1.id
            LEFT JOIN program_sam_spending ps ON p.id = ps.program_id
            WHERE p.id IN ({})
            GROUP BY a1.agency_name
            HAVING program_count > 0
        )
        SELECT 
            agency_title as title,
            program_count as total_num_programs,
            ROUND(total_obs, 0) as total_obs
        FROM program_totals
        ORDER BY total_obs DESC
    """.format(','.join('?' * len(program_ids))), [fiscal_year] + program_ids)
    
    return [dict(row) for row in cursor.fetchall()]

def generate_applicant_type_list(cursor: sqlite3.Cursor, program_ids: List[str]) -> List[Dict[str, Any]]:
    """Generate list of applicant types with program counts for a set of programs."""
    cursor.execute("""
        SELECT 
            c.name as title,
            COUNT(DISTINCT ptc.program_id) as total_num_programs
        FROM category c
        JOIN program_to_category ptc ON c.id = ptc.category_id
        WHERE ptc.category_type = 'applicant'
        AND ptc.program_id IN ({})
        GROUP BY c.name
        HAVING total_num_programs > 0
        ORDER BY total_num_programs DESC
    """.format(','.join('?' * len(program_ids))), program_ids)
    
    return [dict(row) for row in cursor.fetchall()]

def convert_to_url_string(s: str) -> str:
    """Convert a string to URL-friendly format."""
    return str(''.join(c if c.isalnum() else '-' for c in s.lower()))

def generate_category_markdown_files(cursor: sqlite3.Cursor, output_dir: str, fiscal_year: str):
    """Generate markdown files for categories."""
    ensure_directory_exists(output_dir)
    
    # Get all parent categories
    cursor.execute("""
        SELECT DISTINCT 
            c.parent_id as id,
            c.parent_id as title
        FROM category c
        WHERE c.type = 'category'
        AND c.parent_id IS NOT NULL
    """)
    
    parent_categories = cursor.fetchall()
    for parent in parent_categories:
        # Get all programs in this category (including subcategories)
        cursor.execute("""
            SELECT DISTINCT p.id
            FROM program p
            JOIN program_to_category ptc ON p.id = ptc.program_id
            JOIN category c ON ptc.category_id = c.id
            WHERE c.parent_id = ?
            AND ptc.category_type = 'category'
        """, (parent['id'],))
        
        program_ids = [row['id'] for row in cursor.fetchall()]
        if not program_ids:
            continue
            
        # Get subcategories with their stats
        cursor.execute("""
            SELECT 
                c.name as title,
                COUNT(DISTINCT ptc.program_id) as total_num_programs,
                COALESCE(SUM(CASE 
                    WHEN ps.fiscal_year = ? AND ps.is_actual = 1 
                    THEN ps.amount 
                    ELSE 0 
                END), 0) as total_obs
            FROM category c
            JOIN program_to_category ptc ON c.id = ptc.category_id
            LEFT JOIN program_sam_spending ps ON ptc.program_id = ps.program_id
            WHERE c.parent_id = ?
            AND ptc.category_type = 'category'
            GROUP BY c.name
            HAVING total_num_programs > 0
        """, (fiscal_year, parent['id']))
        
        subcats = [dict(row) for row in cursor.fetchall()]
        
        # Calculate category totals
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT p.id) as total_num_programs,
                COALESCE(SUM(CASE 
                    WHEN ps.fiscal_year = ? AND ps.is_actual = 1 
                    THEN ps.amount 
                    ELSE 0 
                END), 0) as total_obs,
                COUNT(DISTINCT a1.agency_name) as total_num_agencies,
                COUNT(DISTINCT c_app.name) as total_num_applicant_types
            FROM program p
            JOIN program_to_category ptc ON p.id = ptc.program_id
            JOIN category c ON ptc.category_id = c.id
            LEFT JOIN program_sam_spending ps ON p.id = ps.program_id
            LEFT JOIN agency a ON p.agency_id = a.id
            LEFT JOIN agency a1 ON a.tier_1_agency_id = a1.id
            LEFT JOIN program_to_category ptc_app ON p.id = ptc_app.program_id AND ptc_app.category_type = 'applicant'
            LEFT JOIN category c_app ON ptc_app.category_id = c_app.id
            WHERE c.parent_id = ?
            AND ptc.category_type = 'category'
        """, (fiscal_year, parent['id']))
        
        totals = cursor.fetchone()
        
        # Create category data
        display_title = ' '.join(word.capitalize() for word in parent['title'].replace('-', ' ').split())
        category_data = {
            'title': display_title,
            'permalink': f"/category/{convert_to_url_string(display_title)}",
            'fiscal_year': fiscal_year,
            'total_num_programs': totals['total_num_programs'],
            'total_num_sub_cats': len(subcats),
            'total_num_agencies': totals['total_num_agencies'],
            'total_num_applicant_types': totals['total_num_applicant_types'],
            'total_obs': float(totals['total_obs']),
            'sub_cats': json.dumps([{
                'title': sub['title'],
                'permalink': f"/category/{convert_to_url_string(display_title)}/{convert_to_url_string(sub['title'])}",
                'total_num_programs': sub['total_num_programs'],
                'total_obs': float(sub['total_obs'])
            } for sub in subcats], separators=(',', ':')),
            'agencies': json.dumps(generate_agency_list(cursor, program_ids, fiscal_year), separators=(',', ':')),
            'applicant_types': json.dumps(generate_applicant_type_list(cursor, program_ids), separators=(',', ':'))
        }
        
        # Write category markdown file
        file_path = os.path.join(output_dir, f"{convert_to_url_string(display_title)}.md")
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write('---\n')
            yaml.dump(category_data, file, allow_unicode=True)
            file.write('---\n')
        
        print(f"Created category markdown file for {display_title}")

def generate_subcategory_markdown_files(cursor: sqlite3.Cursor, output_dir: str, fiscal_year: str):
    """Generate markdown files for subcategories."""
    ensure_directory_exists(output_dir)
    
    # Get all subcategories
    cursor.execute("""
        SELECT DISTINCT 
            c.id,
            c.name as title,
            c.parent_id,
            pc.name as parent_title
        FROM category c
        JOIN category pc ON c.parent_id = pc.id
        WHERE c.type = 'category'
        AND c.parent_id IS NOT NULL
    """)
    
    subcategories = cursor.fetchall()
    for subcat in subcategories:
        # Get all programs in this subcategory
        cursor.execute("""
            SELECT DISTINCT 
                p.id,
                p.name as title,
                p.popular_name,
                a1.agency_name as agency_name,
                COALESCE(ps.amount, 0) as total_obs
            FROM program p
            JOIN program_to_category ptc ON p.id = ptc.program_id
            LEFT JOIN agency a ON p.agency_id = a.id
            LEFT JOIN agency a1 ON a.tier_1_agency_id = a1.id
            LEFT JOIN program_sam_spending ps ON p.id = ps.program_id 
                AND ps.fiscal_year = ? 
                AND ps.is_actual = 1
            WHERE ptc.category_id = ?
            AND ptc.category_type = 'category'
        """, (fiscal_year, subcat['id']))
        
        programs = cursor.fetchall()
        if not programs:
            continue
        
        program_ids = [p['id'] for p in programs]
        
        # Calculate subcategory totals including agency and applicant type counts
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT p.id) as total_num_programs,
                COALESCE(SUM(CASE 
                    WHEN ps.fiscal_year = ? AND ps.is_actual = 1 
                    THEN ps.amount 
                    ELSE 0 
                END), 0) as total_obs,
                COUNT(DISTINCT a1.agency_name) as total_num_agencies,
                COUNT(DISTINCT c_app.name) as total_num_applicant_types
            FROM program p
            JOIN program_to_category ptc ON p.id = ptc.program_id
            LEFT JOIN program_sam_spending ps ON p.id = ps.program_id
            LEFT JOIN agency a ON p.agency_id = a.id
            LEFT JOIN agency a1 ON a.tier_1_agency_id = a1.id
            LEFT JOIN program_to_category ptc_app ON p.id = ptc_app.program_id AND ptc_app.category_type = 'applicant'
            LEFT JOIN category c_app ON ptc_app.category_id = c_app.id
            WHERE ptc.category_id = ?
            AND ptc.category_type = 'category'
        """, (fiscal_year, subcat['id']))
        
        totals = cursor.fetchone()
        
        # Create subcategory data
        parent_title = ' '.join(word.capitalize() for word in subcat['parent_title'].replace('-', ' ').split())
        subcategory_data = {
            'title': subcat['title'],
            'permalink': f"/category/{convert_to_url_string(parent_title)}/{convert_to_url_string(subcat['title'])}",
            'parent_title': parent_title,
            'parent_permalink': f"/category/{convert_to_url_string(parent_title)}",
            'fiscal_year': fiscal_year,
            'total_num_programs': totals['total_num_programs'],
            'total_num_agencies': totals['total_num_agencies'],
            'total_num_applicant_types': totals['total_num_applicant_types'],
            'total_obs': float(totals['total_obs']),
            'agencies': json.dumps(generate_agency_list(cursor, program_ids, fiscal_year), separators=(',', ':')),
            'applicant_types': json.dumps(generate_applicant_type_list(cursor, program_ids), separators=(',', ':')),
            'programs': json.dumps([{
                'permalink': f"/program/{p['id']}",
                'title': p['title'],
                'popular_name': p['popular_name'],
                'agency': p['agency_name'] or 'Unspecified',
                'total_obs': float(p['total_obs'])
            } for p in programs], separators=(',', ':'))
        }
        
        # Write subcategory markdown file
        file_path = os.path.join(output_dir, 
            f"{convert_to_url_string(parent_title)}---{convert_to_url_string(subcat['title'])}.md")
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write('---\n')
            yaml.dump(subcategory_data, file, allow_unicode=True)
            file.write('---\n')
        
        print(f"Created subcategory markdown file for {subcat['title']}")

def generate_program_data(cursor: sqlite3.Cursor, fiscal_years: list[str]) -> List[Dict[str, Any]]:
    """
    Generate comprehensive program data that can be reused across different generation functions.
    Returns a list of dictionaries containing all necessary program information.
    """
    programs_data = []
    
    # Get base program information
    cursor.execute("""
        SELECT 
            p.id,
            p.name,
            p.popular_name,
            p.objective,
            p.sam_url,
            p.usaspending_awards_url as usaspending_url,
            p.grants_url,
            p.program_type,
            (SELECT a2.agency_name 
             FROM agency a2 
             WHERE a2.id = a.tier_1_agency_id) as top_agency_name,
            (SELECT a2.agency_name 
             FROM agency a2 
             WHERE a2.id = a.tier_2_agency_id) as sub_agency_name
        FROM program p
        LEFT JOIN agency a ON p.agency_id = a.id
    """)
    
    base_programs = cursor.fetchall()
    
    for program in base_programs:

        # Get all categories with single query and print raw results
        cursor.execute("""
            SELECT DISTINCT
                ptc.category_type,
                c.name as category_name,
                pc.name as parent_category_name
            FROM program_to_category ptc
            JOIN category c ON ptc.category_id = c.id
            LEFT JOIN category pc ON c.parent_id = pc.id
            WHERE ptc.program_id = ?
        """, (program['id'],))
        
        categories = cursor.fetchall()
        
        # Get obligations data for all fiscal years
        obligations = get_obligations_data(cursor, program['id'], fiscal_years)
        
        # Get program results
        cursor.execute("""
            SELECT fiscal_year, result 
            FROM program_result 
            WHERE program_id = ?
            ORDER BY fiscal_year
        """, (program['id'],))
        results = [{'year': str(row['fiscal_year']), 'description': row['result']} 
                  for row in cursor.fetchall()]
        
        # Get program authorizations
        cursor.execute("""
            SELECT text, url 
            FROM program_authorization 
            WHERE program_id = ?
        """, (program['id'],))
        authorizations = [row['text'] for row in cursor.fetchall()]
        
        # Use sets to prevent duplicates when organizing categories
        program_categories = {
            'assistance': set(),
            'beneficiary': set(),
            'applicant': set(),
            'categories': set()
        }
        
        for cat in categories:
            if cat['category_type'] in ['assistance', 'beneficiary', 'applicant']:
                program_categories[cat['category_type']].add(cat['category_name'])
            elif cat['category_type'] == 'category':
                if cat['parent_category_name']:
                    program_categories['categories'].add(
                        f"{cat['parent_category_name']} - {cat['category_name']}"
                    )
                else:
                    program_categories['categories'].add(cat['category_name'])
        
        # Create comprehensive program data
        program_data = {
            'id': program['id'],
            'name': program['name'],
            'popular_name': program['popular_name'],
            'objective': program['objective'],
            'sam_url': program['sam_url'],
            'usaspending_url': program['usaspending_url'],
            'grants_url': program['grants_url'],
            'top_agency_name': program['top_agency_name'],
            'sub_agency_name': program['sub_agency_name'],
            'assistance_types': sorted(list(program_categories['assistance'])),
            'beneficiary_types': sorted(list(program_categories['beneficiary'])),
            'applicant_types': sorted(list(program_categories['applicant'])),
            'categories': sorted(list(program_categories['categories'])),
            'obligations': obligations,
            'results': results,
            'authorizations': authorizations
        }
        
        programs_data.append(program_data)

    print("Completed program object creation")

    return programs_data

def generate_shared_data(cursor: sqlite3.Cursor) -> Dict[str, Any]:
    """
    Generate shared data used across multiple pages.
    Returns a dictionary containing agencies, applicant types, and categories data.
    """
    # Get CFO agencies
    cursor.execute("""
        SELECT DISTINCT 
            a1.id,
            a1.agency_name as title
        FROM program p
        JOIN agency a ON p.agency_id = a.id
        JOIN agency a1 ON a.tier_1_agency_id = a1.id
        WHERE a1.is_cfo_act_agency = 1
        AND a.tier_1_agency_id IS NOT NULL
        ORDER BY title
    """)
    
    cfo_agencies = []
    for row in cursor.fetchall():
        if not row['title']:
            continue
            
        agency = {'title': row['title']}
        
        # Get sub-agencies
        cursor.execute("""
            SELECT DISTINCT
                (SELECT a2.agency_name 
                 FROM agency a2 
                 WHERE a2.id = a.tier_2_agency_id) as title
            FROM program p
            JOIN agency a ON p.agency_id = a.id
            WHERE a.tier_1_agency_id = ?
            AND a.tier_2_agency_id IS NOT NULL
            ORDER BY title
        """, (row['id'],))
        
        sub_agencies = [{'title': sub_row['title']} 
                       for sub_row in cursor.fetchall() 
                       if sub_row['title']]
        
        if sub_agencies:
            agency['sub_categories'] = sub_agencies
            
        cfo_agencies.append(agency)
    
    # Get non-CFO agencies (same query but is_cfo_act_agency = 0)
    cursor.execute("""
        SELECT DISTINCT 
            a1.id,
            a1.agency_name as title
        FROM program p
        JOIN agency a ON p.agency_id = a.id
        JOIN agency a1 ON a.tier_1_agency_id = a1.id
        WHERE a1.is_cfo_act_agency = 0
        AND a.tier_1_agency_id IS NOT NULL
        ORDER BY title
    """)
    
    other_agencies = []
    for row in cursor.fetchall():
        if not row['title']:
            continue
            
        agency = {'title': row['title']}
        
        cursor.execute("""
            SELECT DISTINCT
                (SELECT a2.agency_name 
                 FROM agency a2 
                 WHERE a2.id = a.tier_2_agency_id) as title
            FROM program p
            JOIN agency a ON p.agency_id = a.id
            WHERE a.tier_1_agency_id = ?
            AND a.tier_2_agency_id IS NOT NULL
            ORDER BY title
        """, (row['id'],))
        
        sub_agencies = [{'title': sub_row['title']} 
                       for sub_row in cursor.fetchall() 
                       if sub_row['title']]
        
        if sub_agencies:
            agency['sub_categories'] = sub_agencies
            
        other_agencies.append(agency)
    
    # Get simple categories for applicants
    cursor.execute("""
        SELECT DISTINCT 
            c.name as title
        FROM program p
        JOIN program_to_category ptc ON p.id = ptc.program_id
        JOIN category c ON ptc.category_id = c.id
        WHERE ptc.category_type = 'applicant'
        ORDER BY c.name
    """)
    applicant_types = [{'title': row['title']} for row in cursor.fetchall()]
    
    # Get simple categories for assistance types
    cursor.execute("""
        SELECT DISTINCT 
            c.name as title
        FROM program p
        JOIN program_to_category ptc ON p.id = ptc.program_id
        JOIN category c ON ptc.category_id = c.id
        WHERE ptc.category_type = 'assistance'
        ORDER BY c.name
    """)
    assistance_types = [{'title': row['title']} for row in cursor.fetchall()]

    # Get simple categories for beneficiary types
    cursor.execute("""
        SELECT DISTINCT 
            c.name as title
        FROM program p
        JOIN program_to_category ptc ON p.id = ptc.program_id
        JOIN category c ON ptc.category_id = c.id
        WHERE ptc.category_type = 'beneficiary'
        ORDER BY c.name
    """)
    beneficiary_types = [{'title': row['title']} for row in cursor.fetchall()]
    
    # Get categories with subcategories
    cursor.execute("""
        SELECT DISTINCT 
            pc.id as id,
            pc.name as title
        FROM program p
        JOIN program_to_category ptc ON p.id = ptc.program_id
        JOIN category c ON ptc.category_id = c.id
        JOIN category pc ON c.parent_id = pc.id
        WHERE ptc.category_type = 'category'
        ORDER BY pc.name
    """)
    
    categories = []
    for row in cursor.fetchall():
        if not row['title']:
            continue
            
        category = {'title': row['title']}
        
        cursor.execute("""
            SELECT DISTINCT 
                c.name as title
            FROM program p
            JOIN program_to_category ptc ON p.id = ptc.program_id
            JOIN category c ON ptc.category_id = c.id
            WHERE c.parent_id = ?
            AND ptc.category_type = 'category'
            ORDER BY c.name
        """, (row['id'],))
        
        subcategories = [{'title': sub_row['title']} 
                        for sub_row in cursor.fetchall() 
                        if sub_row['title']]
        
        if subcategories:
            category['sub_categories'] = subcategories
            
        categories.append(category)

    print("Completed shared data creation")
    
    return {
        'cfo_agencies': sorted(cfo_agencies, key=lambda x: x['title']),
        'other_agencies': sorted(other_agencies, key=lambda x: x['title']),
        'applicant_types': applicant_types,
        'assistance_types': assistance_types,
        'beneficiary_types': beneficiary_types,  # Added this line
        'categories': sorted(categories, key=lambda x: x['title'])
    }

def generate_program_markdown_files(output_dir: str, programs_data: List[Dict[str, Any]], fiscal_years: list[str]):
    """Generate individual markdown files for each program using pre-generated data."""
    ensure_directory_exists(output_dir)
    
    for program in programs_data:
        # Create listing dictionary using pre-generated data
        listing = {
            'title': program['name'],
            'layout': 'program',
            'permalink': f"/program/{program['id']}.html",
            'fiscal_year': fiscal_years[0],
            'cfda': program['id'],
            'objective': program['objective'],
            'sam_url': program['sam_url'],
            'usaspending_url': program['usaspending_url'],
            'grants_url': program['grants_url'],
            'popular_name': program['popular_name'] if program['popular_name'] else '',
            'assistance_types': program['assistance_types'],
            'beneficiary_types': program['beneficiary_types'],
            'applicant_types': program['applicant_types'],
            'categories': program['categories'],
            'agency': program['top_agency_name'] or 'Unspecified',
            'sub-agency': program['sub_agency_name'] or 'N/A',
            'obligations': json.dumps(program['obligations'], separators=(',', ':')),
            'results': program['results'],
            'authorizations': program['authorizations']
        }

        # Write markdown file
        markdown_file_path = os.path.join(output_dir, f"{program['id']}.md")
        with open(markdown_file_path, 'w', encoding='utf-8') as file:
            file.write('---\n')
            yaml.dump(listing, file, allow_unicode=True)
            file.write('---\n')
        
    print(f"Created markdown files for {len(programs_data)} programs")

def generate_search_page(output_path: str, shared_data: Dict[str, Any], fiscal_year: str):
    """Generate the search page using pre-generated shared data."""
    search_page = {
        'title': 'Program search',
        'layout': 'search',
        'permalink': '/search.html',
        'fiscal_year': fiscal_year,
        'cfo_agencies': shared_data['cfo_agencies'],
        'other_agencies': shared_data['other_agencies'],
        'applicant_types': shared_data['applicant_types'],
        'assistance_types': shared_data['assistance_types'],
        'beneficiary_types': shared_data['beneficiary_types'],
        'categories': shared_data['categories']
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write('---\n')
        yaml.dump(search_page, file, allow_unicode=True)
        file.write('---\n')
    print("Successfully generated search page")

def generate_home_page(output_path: str, shared_data: Dict[str, Any], fiscal_year: str):
    """Generate the home page using pre-generated shared data."""
    page = {
        'title': 'Home',
        'layout': 'home',
        'permalink': '/',
        'fiscal_year': fiscal_year,
        'cfo_agencies': shared_data['cfo_agencies'],
        'other_agencies': shared_data['other_agencies'],
        'applicant_types': shared_data['applicant_types'],
        'program_types': shared_data['assistance_types'],
        'categories': shared_data['categories']
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write('---\n')
        yaml.dump(page, file, allow_unicode=True)
        file.write('---\n')
    print("Successfully generated home page")

def generate_programs_table_json(output_path: str, programs_data: List[Dict[str, Any]], fiscal_year: str):
    """Generate the programs table JSON file using pre-generated data."""
    programs_json = []
    
    for program in programs_data:
        # Get the current fiscal year's obligation amount
        current_year_obligation = next(
            (obl['sam_actual'] or obl['sam_estimate'] or 0 
             for obl in program['obligations'] 
             if obl['x'] == fiscal_year), 
            0
        )
        
        # Format categories with parent-child relationship
        categories = []
        for cat in program['categories']:
            parts = cat.split(' - ', 1)
            if len(parts) == 2:
                categories.append({
                    'title': parts[0],
                    'subCategory': {'title': parts[1]}
                })
        
        program_json = {
            'cfda': program['id'],
            'title': program['name'],
            'permalink': f"/program/{program['id']}",
            'obligations': float(current_year_obligation),
            'objectives': program['objective'],
            'popularName': program['popular_name'],
            'agency': {
                'title': program['top_agency_name'] or 'Unspecified',
                'subAgency': {
                    'title': program['sub_agency_name'] or 'N/A'
                }
            },
            'assistanceTypes': program['assistance_types'],
            'applicantTypes': program['applicant_types'],
            'categories': categories
        }
        
        programs_json.append(program_json)
    
    # Sort by obligations descending
    programs_json.sort(key=lambda x: x['obligations'], reverse=True)
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as file:
        json.dump(programs_json, file, separators=(',', ':'))
    
    print(f"Successfully generated programs table JSON with {len(programs_json)} programs")

def generate_category_page(cursor: sqlite3.Cursor, programs_data: List[Dict[str, Any]], 
                         output_path: str, fiscal_year: str):
    """Generate the category page using a mix of pre-generated data and database queries."""
    # Get all unique categories and their hierarchies
    categories = set()
    for program in programs_data:
        for category in program['categories']:
            if ' - ' in category:
                parent = category.split(' - ')[0]
                categories.add(parent)
    categories = sorted(list(categories))
    
    # Calculate totals and category stats
    category_stats = {}
    total_programs = len(programs_data)
    total_obs = sum(
        obl['sam_actual'] or obl['sam_estimate'] or 0 
        for prog in programs_data 
        for obl in prog['obligations'] 
        if obl['x'] == fiscal_year
    )
    
    for category in categories:
        category_programs = [
            p for p in programs_data 
            if any(c.startswith(category + ' - ') for c in p['categories'])
        ]
        
        category_stats[category] = {
            'title': category,
            'total_num_programs': len(category_programs),
            'total_obs': sum(
                obl['sam_actual'] or obl['sam_estimate'] or 0 
                for prog in category_programs 
                for obl in prog['obligations'] 
                if obl['x'] == fiscal_year
            ),
            'permalink': f"/category/{convert_to_url_string(category)}"
        }
    
    # Prepare categories list and JSON
    categories_list = [{
        'title': cat,
        'permalink': f"/category/{convert_to_url_string(cat)}"
    } for cat in categories]
    
    categories_json = json.dumps(
        sorted(list(category_stats.values()), 
        key=lambda x: x['total_obs'], 
        reverse=True), 
        separators=(',', ':')
    )
    
    category_page = {
        'title': 'Categories',
        'layout': 'category-index',
        'permalink': '/category.html',
        'fiscal_year': fiscal_year,
        'total_num_programs': total_programs,
        'total_obs': total_obs,
        'categories': categories_list,
        'categories_json': categories_json
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write('---\n')
        yaml.dump(category_page, file, allow_unicode=True)
        file.write('---\n')
    
    print(f"Successfully generated category page")

def generate_program_csv(output_path: str, programs_data: List[Dict[str, Any]], fiscal_years: list[str]):
    """Generate CSV file containing all program data using pre-generated data."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as file:
        csvwriter = csv.writer(file)
        csvwriter.writerow([
            'al_number',
            'title',
            'popular_name',
            'agency',
            'sub-agency',
            'objective',
            'sam_url',
            'usaspending_url',
            'grants_url',
            'assistance_types',
            'beneficiary_types',
            'applicant_types',
            'categories',
            'obligations'
        ])

        for program in programs_data:
            csvwriter.writerow([
                program['id'],
                program['name'],
                program['popular_name'] or '',
                program['top_agency_name'] or 'Unspecified',
                program['sub_agency_name'] or 'N/A',
                program['objective'],
                program['sam_url'],
                program['usaspending_url'],
                program['grants_url'],
                ','.join(program['assistance_types']),
                ','.join(program['beneficiary_types']),
                ','.join(program['applicant_types']),
                ','.join(program['categories']),
                json.dumps(program['obligations'], separators=(',', ':'))
            ])
    
    print(f"Generated CSV file with {len(programs_data)} programs")
    

try:
    conn = sqlite3.connect(full_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    programs_data = generate_program_data(cursor, FISCAL_YEARS)

    shared_data = generate_shared_data(cursor)

    generate_program_markdown_files(MARKDOWN_DIR, programs_data, FISCAL_YEARS)

    generate_program_csv('../website/assets/files/all-program-data.csv', programs_data, FISCAL_YEARS)
    
    search_path = os.path.join('../website', 'pages', 'search.md')
    generate_search_page(search_path, shared_data, FISCAL_YEARS[0])
    
    category_path = os.path.join('../website', 'pages', 'category.md')
    generate_category_page(cursor, programs_data, category_path, FISCAL_YEARS[0])
    
    home_path = os.path.join('../website', 'pages', 'home.md')
    generate_home_page(home_path, shared_data, FISCAL_YEARS[0])
    
    programs_json_path = os.path.join('../website', 'data', 'programs-table.json')
    generate_programs_table_json(programs_json_path, programs_data, FISCAL_YEARS[0])
    
    category_dir = os.path.join('../website', '_category')
    generate_category_markdown_files(cursor, category_dir, FISCAL_YEARS[0])
    
    subcategory_dir = os.path.join('../website', '_subcategory')
    generate_subcategory_markdown_files(cursor, subcategory_dir, FISCAL_YEARS[0])
    

except sqlite3.Error as e:
    print(f"Database error occurred: {e}")
    raise e
except Exception as e:
    print(f"An error occurred: {e}")
    raise e
finally:
    if 'conn' in locals():
        conn.close()