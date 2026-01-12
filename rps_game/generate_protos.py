"""
Script to generate Python code from protobuf files
Run this before starting the servers or client
"""
import subprocess
import os

def generate_protos():
    """Generate Python code from .proto files"""
    
    # Create protos directory if it doesn't exist
    os.makedirs('protos', exist_ok=True)
    
    # Generate from game_service.proto
    print("Generating game_service protobuf files...")
    subprocess.run([
        'python', '-m', 'grpc_tools.protoc',
        '-I.', 
        '--python_out=.',
        '--grpc_python_out=.',
        'protos/game_service.proto'
    ], check=True)
    
    # Generate from orm.proto
    print("Generating orm protobuf files...")
    subprocess.run([
        'python', '-m', 'grpc_tools.protoc',
        '-I.',
        '--python_out=.',
        '--grpc_python_out=.',
        'protos/orm.proto'
    ], check=True)
    
    # Create __init__.py in protos directory
    init_file = os.path.join('protos', '__init__.py')
    if not os.path.exists(init_file):
        with open(init_file, 'w') as f:
            f.write('# Generated protobuf package\n')
    
    print("✓ Protobuf files generated successfully!")
    print("\nGenerated files:")
    print("  - protos/game_service_pb2.py")
    print("  - protos/game_service_pb2_grpc.py")
    print("  - protos/orm_pb2.py")
    print("  - protos/orm_pb2_grpc.py")

if __name__ == '__main__':
    generate_protos()
