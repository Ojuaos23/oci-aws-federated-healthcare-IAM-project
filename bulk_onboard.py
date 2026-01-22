#!/usr/bin/env python3
"""
Healthcare IAM - Bulk User Onboarding
Automated user provisioning for healthcare roles
"""

import oci
import csv
import sys
import argparse
from datetime import datetime
from typing import List, Dict
import json

class HealthcareUserManager:
    """Manages user lifecycle for healthcare IAM system"""
    
    # Healthcare role to OCI group mapping
    ROLE_MAPPINGS = {
        'SecurityAdmin': 'HC-Security-Admins',
        'CloudEngineer': 'HC-Cloud-Engineers',
        'ClinicalAdmin': 'HC-Clinical-App-Admins',
        'ComplianceAuditor': 'HC-Compliance-Auditors',
        'Developer': 'HC-Clinical-Developers',
        'DataAnalyst': 'HC-Data-Analysts'
    }
    
    def __init__(self, config_file="./config", profile="DEFAULT"):
        """Initialize OCI clients"""
        print("🏥 Healthcare IAM User Manager")
        print("=" * 60)
        
        self.config = oci.config.from_file(config_file, profile)
        self.identity_client = oci.identity.IdentityClient(self.config)
        self.tenancy_id = self.config["tenancy"]
        
        # Cache groups
        self.group_cache = {}
        self._load_groups()
    
    def _load_groups(self):
        """Load and cache all IAM groups"""
        print("\n📋 Loading IAM groups...")
        
        try:
            groups = self.identity_client.list_groups(
                compartment_id=self.tenancy_id
            ).data
            
            for group in groups:
                self.group_cache[group.name] = group.id
            
            print(f"✓ Loaded {len(self.group_cache)} groups")
            
            # Display healthcare groups
            hc_groups = [g for g in self.group_cache.keys() if g.startswith('HC-')]
            if hc_groups:
                print(f"  Healthcare groups: {', '.join(hc_groups)}")
        
        except Exception as e:
            print(f"✗ Error loading groups: {str(e)}")
            sys.exit(1)
    
    def create_user(self, username: str, email: str, role: str, 
                   description: str = "", department: str = "") -> Dict:
        """
        Create a healthcare user with appropriate role
        
        Args:
            username: User's login name
            email: User's email address
            role: Healthcare role (SecurityAdmin, ClinicalAdmin, etc.)
            description: Optional user description
            department: User's department
        
        Returns:
            Dict with operation results
        """
        result = {
            'username': username,
            'email': email,
            'role': role,
            'department': department,
            'success': False,
            'user_ocid': None,
            'group_name': None,
            'error': None,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Map role to group
        group_name = self.ROLE_MAPPINGS.get(role)
        if not group_name:
            result['error'] = f"Invalid role: {role}. Valid roles: {', '.join(self.ROLE_MAPPINGS.keys())}"
            return result
        
        if group_name not in self.group_cache:
            result['error'] = f"Group not found in OCI: {group_name}"
            return result
        
        result['group_name'] = group_name
        
        try:
            # Build user description
            user_desc = description or f"Healthcare {role}"
            if department:
                user_desc += f" - {department}"
            
            # Create user
            user_details = oci.identity.models.CreateUserDetails(
                compartment_id=self.tenancy_id,
                name=username,
                description=user_desc,
                email=email,
                freeform_tags={
                    'Role': role,
                    'Department': department or 'Unspecified',
                    'CreatedBy': 'Automated-Provisioning',
                    'CreatedDate': datetime.utcnow().strftime('%Y-%m-%d')
                }
            )
            
            user_response = self.identity_client.create_user(user_details)
            user_ocid = user_response.data.id
            result['user_ocid'] = user_ocid
            
            print(f"  ✓ User created: {username}")
            
            # Add to appropriate group
            group_ocid = self.group_cache[group_name]
            add_user_details = oci.identity.models.AddUserToGroupDetails(
                user_id=user_ocid,
                group_id=group_ocid
            )
            self.identity_client.add_user_to_group(add_user_details)
            
            print(f"  ✓ Added to group: {group_name}")
            
            # Configure user capabilities
            capabilities = oci.identity.models.UpdateUserCapabilitiesDetails(
                can_use_console_password=True,  # Enable console access
                can_use_api_keys=False  # Disable API keys (use federation)
            )
            self.identity_client.update_user_capabilities(user_ocid, capabilities)
            
            print(f"  ✓ Configured capabilities (Console: Yes, API Keys: No)")
            
            result['success'] = True
            return result
            
        except oci.exceptions.ServiceError as e:
            result['error'] = f"OCI Service Error: {e.message}"
            return result
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            return result
    
    def bulk_create_from_csv(self, csv_file: str) -> List[Dict]:
        """
        Create multiple users from CSV file
        
        CSV Format:
        username,email,role,department,description
        
        Example:
        john.doe,john.doe@hospital.com,ClinicalAdmin,Cardiology,Chief of Cardiology
        """
        results = []
        
        print(f"\n📄 Processing CSV file: {csv_file}")
        print("-" * 60)
        
        try:
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                
                # Validate headers
                required_headers = {'username', 'email', 'role'}
                if not required_headers.issubset(set(reader.fieldnames)):
                    print(f"✗ Error: CSV must have headers: {', '.join(required_headers)}")
                    sys.exit(1)
                
                for idx, row in enumerate(reader, 1):
                    username = row['username'].strip()
                    email = row['email'].strip()
                    role = row['role'].strip()
                    department = row.get('department', '').strip()
                    description = row.get('description', '').strip()
                    
                    print(f"\n[{idx}] Processing: {username} ({role})")
                    
                    result = self.create_user(
                        username=username,
                        email=email,
                        role=role,
                        department=department,
                        description=description
                    )
                    
                    results.append(result)
                    
                    if result['success']:
                        print(f"  ✓ SUCCESS - OCID: {result['user_ocid']}")
                    else:
                        print(f"  ✗ FAILED - {result['error']}")
        
        except FileNotFoundError:
            print(f"✗ Error: CSV file not found: {csv_file}")
            sys.exit(1)
        except Exception as e:
            print(f"✗ Error reading CSV: {str(e)}")
            sys.exit(1)
        
        return results
    
    def generate_report(self, results: List[Dict], output_file: str = None):
        """Generate summary report of bulk operation"""
        
        total = len(results)
        successful = sum(1 for r in results if r['success'])
        failed = total - successful
        
        print("\n" + "=" * 60)
        print("📊 BULK ONBOARDING SUMMARY")
        print("=" * 60)
        print(f"Total users processed: {total}")
        print(f"✓ Successful: {successful} ({successful/total*100:.1f}%)" if total > 0 else "No users processed")
        print(f"✗ Failed: {failed} ({failed/total*100:.1f}%)" if total > 0 else "")
        print("=" * 60)
        
        # Show role breakdown
        if successful > 0:
            role_counts = {}
            for r in results:
                if r['success']:
                    role = r['role']
                    role_counts[role] = role_counts.get(role, 0) + 1
            
            print("\n📋 Users by Role:")
            for role, count in sorted(role_counts.items()):
                print(f"  {role}: {count}")
        
        # Show failures
        if failed > 0:
            print("\n❌ Failed Users:")
            for r in results:
                if not r['success']:
                    print(f"  - {r['username']} ({r['role']}): {r['error']}")
        
        # Write detailed CSV report
        if output_file:
            try:
                with open(output_file, 'w', newline='') as f:
                    fieldnames = ['timestamp', 'username', 'email', 'role', 
                                'department', 'group_name', 'success', 
                                'user_ocid', 'error']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(results)
                
                print(f"\n✓ Detailed report saved: {output_file}")
            except Exception as e:
                print(f"✗ Error writing report: {str(e)}")
        
        # Write JSON audit log
        audit_file = output_file.replace('.csv', '_audit.json') if output_file else 'audit.json'
        try:
            with open(audit_file, 'w') as f:
                json.dump({
                    'operation': 'bulk_user_onboarding',
                    'timestamp': datetime.utcnow().isoformat(),
                    'summary': {
                        'total': total,
                        'successful': successful,
                        'failed': failed
                    },
                    'results': results
                }, f, indent=2)
            
            print(f"✓ Audit log saved: {audit_file}")
        except Exception as e:
            print(f"✗ Error writing audit log: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description='Healthcare IAM - Bulk User Onboarding',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Onboard users from CSV
  python3 bulk_onboard.py --csv users.csv --report results.csv
  
  # Use custom OCI profile
  python3 bulk_onboard.py --csv users.csv --profile PRODUCTION

Valid Roles:
  SecurityAdmin       - Security operations and IAM management
  CloudEngineer       - Infrastructure and platform management
  ClinicalAdmin       - Clinical application administration
  ComplianceAuditor   - Read-only audit and compliance access
  Developer           - Development environment access
  DataAnalyst         - Analytics and reporting access
        """
    )
    
    parser.add_argument(
        '--csv',
        required=True,
        help='Path to CSV file with user data'
    )
    parser.add_argument(
        '--report',
        default='onboarding_report.csv',
        help='Output file for detailed report (default: onboarding_report.csv)'
    )
    parser.add_argument(
        '--profile',
        default='DEFAULT',
        help='OCI config profile to use (default: DEFAULT)'
    )
    
    args = parser.parse_args()
    
    # Create manager and process users
    manager = HealthcareUserManager(profile=args.profile)
    results = manager.bulk_create_from_csv(args.csv)
    manager.generate_report(results, args.report)
    
    print("\n✅ Bulk onboarding complete!")
    print("\nNext Steps:")
    print("1. Users will receive password reset emails")
    print("2. Users must configure MFA on first login")
    print("3. Users can access via AWS IAM Identity Center SSO")
    print("4. Review the audit log for compliance records")


if __name__ == "__main__":
    main()