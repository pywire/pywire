import React from 'react';
import { CheckCircle, Circle } from 'lucide-react';
import type { SuccessCriteria } from './types';
import type { ValidationResult } from './SuccessValidator';

interface TasksChecklistProps {
    criteria?: SuccessCriteria[];
    results?: ValidationResult[];
}

export const TasksChecklist: React.FC<TasksChecklistProps> = ({ criteria, results }) => {
    if (!criteria || criteria.length === 0) return null;

    return (
        <div className="pw-tasks-checklist">
            <h3 className="pw-tasks-title">Tasks</h3>
            <ul className="pw-tasks-list">
                {criteria.map((criterion, index) => {
                    const result = results?.[index];
                    const isCompleted = result?.passed ?? false;

                    // Prefer description from result (which might come from validator logic) or criteria
                    const description = criterion.description || `Task ${index + 1}`;

                    return (
                        <li key={index} className={`pw-task-item ${isCompleted ? 'completed' : ''}`}>
                            <div className="pw-task-icon">
                                {isCompleted ? (
                                    <CheckCircle size={18} className="text-green-500" />
                                ) : (
                                    <Circle size={18} className="text-gray-500" />
                                )}
                            </div>
                            <span className="pw-task-desc">{description}</span>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
};
