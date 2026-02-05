import React from 'react';
import { X } from 'lucide-react';

interface ModalProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    children: React.ReactNode;
}

export const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, children }) => {
    if (!isOpen) return null;

    return (
        <div className="pw-modal-overlay" onClick={onClose}>
            <div className="pw-modal-content" onClick={(e) => e.stopPropagation()}>
                <div className="pw-modal-header">
                    <h2>{title}</h2>
                    <button className="pw-btn-icon" onClick={onClose}>
                        <X size={18} />
                    </button>
                </div>
                {children}
            </div>
        </div>
    );
};
